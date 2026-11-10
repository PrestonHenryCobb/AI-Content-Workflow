"""Stage 1: find and score candidate cases; keep a deduplicated backlog."""

from __future__ import annotations

import difflib
import json
from datetime import UTC, datetime

from pipeline import prompts
from pipeline.config import REPO_ROOT, Settings
from pipeline.llm import Completer
from pipeline.schemas import Candidates, CaseCandidate
from pipeline.state import State

PUBLISHED = REPO_ROOT / "data" / "published_cases.json"


def published_titles() -> list[str]:
    try:
        data = json.loads(PUBLISHED.read_text())
    except FileNotFoundError:
        return []
    return [str(d["title"] if isinstance(d, dict) else d) for d in data]


def is_duplicate(c: CaseCandidate, known: list[str], cutoff: float = 0.82) -> bool:
    key = c.title.lower()
    return any(difflib.SequenceMatcher(None, key, k.lower()).ratio() >= cutoff for k in known)


def score(c: CaseCandidate) -> float:
    s = c.scores
    return (0.30 * s.intrigue + 0.25 * s.novelty + 0.20 * s.visual
            + 0.25 * s.source_quality - 0.35 * max(0, s.risk - 4))


def eligible(c: CaseCandidate, settings: Settings) -> bool:
    min_age = int(settings.sources.get("min_case_age_years", 10))
    return (datetime.now(UTC).year - c.year >= min_age and c.scores.risk <= 7
            and len(c.sources) >= 1)


def discover(llm: Completer, state: State, *, count: int = 8, hint: str = "",
             job_id: str | None = None, urgent: bool = False) -> list[CaseCandidate]:
    known = published_titles() + [r[0] for r in state.conn.execute(
        "SELECT title FROM cases").fetchall()]
    from pipeline import growth
    from pipeline.analytics import current_mix

    extra = [h for h in (hint and f"Focus: {hint}", growth.discovery_hint(state),
                         growth.request_hint(state)) if h]

    mix = current_mix(state, llm.settings)
    mix_text = ", ".join(f"~{round(v * 100)}% {k.replace('_', ' ')}" for k, v in mix.items())
    prompt = prompts.load(
        "discover", count=count, mix=mix_text,
        min_age=llm.settings.sources.get("min_case_age_years", 10),
        avoid="none", published="; ".join(known[-200:]) or "none",
        hint="\n".join(extra),
    )
    res = llm.complete("discover", prompt, json_schema=Candidates.json_schema(),
                       job_id=job_id, urgent=urgent)
    found = Candidates.model_validate(res.data).candidates
    names = growth.requested_names(state)
    kept = [c.model_copy(update={"requested": growth.is_requested(c, names)})
            for c in found if eligible(c, llm.settings) and not is_duplicate(c, known)]
    with state.tx() as conn:
        for c in kept:
            conn.execute(
                "INSERT OR IGNORE INTO cases (case_id, title, status, score, meta) "
                "VALUES (?, ?, 'candidate', ?, ?)",
                (c.case_id, c.title, score(c), c.model_dump_json()),
            )
    return sorted(kept, key=score, reverse=True)


def next_case(state: State) -> CaseCandidate | None:
    row = state.conn.execute(
        "SELECT meta FROM cases WHERE status = 'candidate' ORDER BY score DESC LIMIT 1"
    ).fetchone()
    return CaseCandidate.model_validate_json(row[0]) if row else None
