"""Single entry point for every Claude call in the pipeline.

Default backend `claude_code` shells out to `claude -p` authenticated with the owner's
Claude Pro subscription (CLAUDE_CODE_OAUTH_TOKEN in CI, or a local `claude` login), so
there is no per-token bill. API-key variables are stripped from the child environment so a
stray ANTHROPIC_API_KEY can never silently switch the pipeline to paid API billing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pipeline.budget import Governor, SubscriptionLimited
from pipeline.config import Settings, StageModel

# Variables that would make `claude` bill an API account instead of the subscription.
_BILLING_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
_LIMIT_RE = re.compile(
    r"(usage limit|limit reached|hit your limit|rate limit|out of (extra )?usage)", re.I
)
_TRANSIENT_RE = re.compile(r"(overloaded|timed? ?out|ECONNRESET|5\d\d)", re.I)

Runner = Callable[..., subprocess.CompletedProcess[str]]


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMResult:
    text: str
    data: Any | None            # parsed structured output when a json_schema was given
    model: str
    input_tokens: int | None
    output_tokens: int | None
    duration_s: float


class Completer(Protocol):
    """What stages need from an LLM client (real `LLM` or `offline.OfflineLLM`)."""

    settings: Settings

    def complete(self, stage_name: str, prompt: str, *, system: str | None = None,
                 json_schema: dict[str, Any] | None = None, job_id: str | None = None,
                 urgent: bool = False, timeout_s: int = 900, add_dirs: Sequence[str] = (),
                 extra_tools: Sequence[str] = ()) -> LLMResult: ...


def child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _BILLING_ENV_VARS}
    env.setdefault("DISABLE_AUTOUPDATER", "1")
    return env


def build_command(stage: StageModel, system: str | None, json_schema: dict[str, Any] | None,
                  claude_bin: str = "claude", add_dirs: Sequence[str] = (),
                  extra_tools: Sequence[str] = ()) -> list[str]:
    tools = list(dict.fromkeys([*stage.tools, *extra_tools]))
    cmd = [claude_bin, "-p", "--output-format", "json", "--model", stage.model,
           "--effort", stage.effort, "--tools", ",".join(tools)]
    if tools:
        # Headless runs can't answer permission prompts; pre-approve exactly these tools.
        cmd += ["--allowedTools", *tools]
    for d in add_dirs:
        cmd += ["--add-dir", d]
    if stage.fallback:
        cmd += ["--fallback-model", stage.fallback]
    if system:
        cmd += ["--system-prompt", system]
    if json_schema is not None:
        cmd += ["--json-schema", json.dumps(json_schema, sort_keys=True)]
    return cmd


class LLM:
    def __init__(self, governor: Governor, runner: Runner = subprocess.run,
                 claude_bin: str = "claude", max_retries: int = 2) -> None:
        self.gov = governor
        self.settings: Settings = governor.settings
        self.runner = runner
        self.claude_bin = claude_bin
        self.max_retries = max_retries

    def complete(
        self,
        stage_name: str,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: dict[str, Any] | None = None,
        job_id: str | None = None,
        urgent: bool = False,
        timeout_s: int = 900,
        add_dirs: Sequence[str] = (),
        extra_tools: Sequence[str] = (),
    ) -> LLMResult:
        stage = self.settings.models.stages[stage_name]
        if self.settings.models.backend == "api":
            raise NotImplementedError(
                "API backend is disabled by design (DECISIONS D14); owner must opt in"
            )
        cmd = build_command(stage, system, json_schema, self.claude_bin, add_dirs, extra_tools)
        last_err = ""
        for attempt in range(self.max_retries + 1):
            self.gov.authorize_llm(stage_name, urgent=urgent)
            t0 = time.monotonic()
            # Empty cwd: no repo CLAUDE.md or settings leak into the call and burn usage.
            with tempfile.TemporaryDirectory(prefix="acw-llm-") as cwd:
                proc = self.runner(cmd, input=prompt, capture_output=True, text=True,
                                   timeout=timeout_s, env=child_env(), cwd=cwd)
            dt = time.monotonic() - t0
            payload = _parse(proc.stdout)
            is_error = proc.returncode != 0 or bool(payload.get("is_error"))
            usage = payload.get("usage") or {}
            if not is_error:
                self.gov.record_llm_call(stage.model, stage_name, ok=True, job_id=job_id,
                                         duration_s=dt,
                                         input_tokens=usage.get("input_tokens"),
                                         output_tokens=usage.get("output_tokens"))
                return _result(payload, stage.model, json_schema, dt)
            last_err = str(payload.get("result") or proc.stderr or proc.stdout)[:500]
            limit = bool(_LIMIT_RE.search(last_err))
            self.gov.record_llm_call(stage.model, stage_name, ok=False, limit_hit=limit,
                                     job_id=job_id, duration_s=dt)
            if limit:
                raise SubscriptionLimited(f"{stage_name}: plan limit hit: {last_err}")
            if not _TRANSIENT_RE.search(last_err) or attempt == self.max_retries:
                break
            time.sleep(2 ** (attempt + 1))
        raise LLMError(f"{stage_name} failed: {last_err}")


def _parse(stdout: str) -> dict[str, Any]:
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return {"is_error": True, "result": stdout}
    return data if isinstance(data, dict) else {"is_error": True, "result": stdout}


def _result(payload: dict[str, Any], model: str, schema: dict[str, Any] | None,
            dt: float) -> LLMResult:
    text = str(payload.get("result") or "")
    data: Any | None = None
    if schema is not None:
        data = payload.get("structured_output")
        if data is None:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise LLMError(f"expected JSON matching schema, got: {text[:200]}") from e
    usage = payload.get("usage") or {}
    return LLMResult(text=text, data=data, model=model,
                     input_tokens=usage.get("input_tokens"),
                     output_tokens=usage.get("output_tokens"), duration_s=dt)


__all__: Sequence[str] = ("LLM", "Completer", "LLMError", "LLMResult", "build_command",
                          "child_env")
