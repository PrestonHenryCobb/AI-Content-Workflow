"""Load versioned prompt templates from prompts/*.md and fill {placeholders}."""

from __future__ import annotations

import re
from pathlib import Path

from pipeline.config import REPO_ROOT

PROMPT_DIR = REPO_ROOT / "prompts"
_VERSION = re.compile(r"<!--\s*version:\s*(\d+)\s*-->")


def load(name: str, **values: object) -> str:
    text = (PROMPT_DIR / f"{name}.md").read_text()
    body = _VERSION.sub("", text, count=1).strip()
    missing = set(re.findall(r"\{(\w+)\}", body)) - set(values)
    if missing:
        raise KeyError(f"prompt {name!r} missing values: {sorted(missing)}")
    for k, v in values.items():
        body = body.replace("{" + k + "}", str(v))
    return body


def version(name: str) -> int:
    m = _VERSION.search((PROMPT_DIR / f"{name}.md").read_text())
    return int(m.group(1)) if m else 0


def voice_guide() -> str:
    return Path(REPO_ROOT / "brand" / "voice_and_tone.md").read_text()
