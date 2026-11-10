import json
import subprocess
from datetime import UTC, datetime

import pytest

from pipeline.budget import Governor, SubscriptionLimited
from pipeline.llm import LLM, LLMError, build_command, child_env

NIGHT = datetime(2026, 11, 12, 7, 0, tzinfo=UTC)


class FakeRunner:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        rc, payload = self.outputs.pop(0)
        out = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")


def make(state, settings, *outputs):
    g = Governor(state, settings, now=NIGHT)
    r = FakeRunner(*outputs)
    llm = LLM(g, runner=r)
    return llm, r, g


OK = (0, {"type": "result", "is_error": False, "result": "hello",
          "usage": {"input_tokens": 10, "output_tokens": 5}})


def test_success_records_call(state, settings):
    llm, r, g = make(state, settings, OK)
    res = llm.complete("script", "write it", system="sys")
    assert res.text == "hello" and res.output_tokens == 5
    assert g.subscription_status().calls_today == 1
    cmd, kw = r.calls[0]
    assert kw["input"] == "write it"
    assert "--system-prompt" in cmd and "sys" in cmd


def test_api_keys_never_reach_child(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth")
    env = child_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth"


def test_command_shape(settings):
    st = settings.models.stages
    cmd = build_command(st["qa_fact"], None, None)
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5"
    assert cmd[cmd.index("--fallback-model") + 1] == "claude-sonnet-5-5"
    assert cmd[cmd.index("--tools") + 1] == ""                 # pure text, no tools
    research = build_command(st["verify"], None, None)
    assert research[research.index("--tools") + 1] == "WebSearch,WebFetch"


def test_structured_output(state, settings):
    payload = {"is_error": False, "result": "", "structured_output": {"ok": True}}
    llm, _, _ = make(state, settings, (0, payload))
    res = llm.complete("metadata", "x", json_schema={"type": "object"})
    assert res.data == {"ok": True}


def test_structured_output_falls_back_to_result_text(state, settings):
    llm, _, _ = make(state, settings, (0, {"is_error": False, "result": '{"a": 1}'}))
    assert llm.complete("metadata", "x", json_schema={"type": "object"}).data == {"a": 1}


def test_plan_limit_raises_and_starts_cooldown(state, settings):
    limited = (1, {"is_error": True, "result": "Claude usage limit reached. Resets 6am"})
    llm, _, g = make(state, settings, limited)
    with pytest.raises(SubscriptionLimited):
        llm.complete("script", "x")
    assert g.subscription_status().cooldown_until is not None


def test_transient_error_retries(state, settings, monkeypatch):
    monkeypatch.setattr("pipeline.llm.time.sleep", lambda s: None)
    llm, r, _ = make(state, settings, (1, {"is_error": True, "result": "API overloaded"}), OK)
    assert llm.complete("script", "x").text == "hello"
    assert len(r.calls) == 2


def test_hard_error_does_not_retry(state, settings):
    llm, r, _ = make(state, settings, (1, {"is_error": True, "result": "invalid model"}))
    with pytest.raises(LLMError):
        llm.complete("script", "x")
    assert len(r.calls) == 1


def test_garbage_stdout_is_error(state, settings):
    llm, _, _ = make(state, settings, (0, "not json"))
    with pytest.raises(LLMError):
        llm.complete("script", "x")
