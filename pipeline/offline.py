"""Offline mode: a stand-in for `claude -p` that returns fixtures for a FICTIONAL test case.

Used by tests and `acw make-short --offline` to exercise the full render chain without
network, subscription usage, or any risk of publishing invented facts about a real case.
Every fixture is marked fictional and uses example.org sources, so nothing here could be
mistaken for research.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from pipeline.budget import Governor
from pipeline.config import Settings
from pipeline.llm import LLMResult

CASE = {
    "case_id": "test-room12-1987", "title": "TEST CASE (fictional): The Room 12 Signal",
    "summary": "Fictional fixture for offline pipeline tests.", "location": "Testville, Nowhere",
    "year": 1987, "category": "unsolved", "sources": ["https://example.org/test-case"],
    "scores": {"intrigue": 8, "novelty": 8, "visual": 8, "source_quality": 8, "risk": 2},
    "risk_notes": "fictional",
}

_CLAIMS = [
    "In this fictional test case, a motel clerk logs a call from Room 12 at 2:14 a.m.",
    "Room 12 had been empty for three days, according to the fictional ledger.",
    "The fictional caller says only one word: a street name nobody recognizes.",
    "A fictional deputy finds the room locked from the inside, TV on static.",
    "The fictional phone line to Room 12 had been disconnected a year earlier.",
    "In the fictional record, the street name matches a road demolished in 1961.",
    "The fictional case file remains open.",
]
FACT_PACK = {
    "case_id": CASE["case_id"], "title": CASE["title"], "location": CASE["location"],
    "year": 1987, "legal_status": "open", "active_trial": False,
    "people": [{"role": "witness", "name": "Test Clerk", "is_minor": False,
                "name_allowed": True}],
    "claims": [{"id": f"c{i + 1}", "text": t,
                "citations": [{"url": "https://example.org/test-a", "quote": t},
                              {"url": "https://example.net/test-b", "quote": t}]}
               for i, t in enumerate(_CLAIMS)],
    "agency_contact": "n/a (fictional)", "sources": ["https://example.org/test-a"],
}

_LINES = [
    ("At 2:14 a.m., a call comes from a room that is empty.", ["c1", "c2"], "s1"),
    ("This is a fictional test case, built to check the machine.", ["c1"], "s2"),
    ("The motel clerk logs it. Room 12. Nobody has stayed there in three days.",
     ["c1", "c2"], "s2"),
    ("The caller says one word. A street name. Nobody in town recognizes it.", ["c3"], "s3"),
    ("A deputy walks the hallway. Room 12 is locked from the inside.", ["c4"], "s4"),
    ("The television is on. Only static. The bed hasn't been touched.", ["c4"], "s5"),
    ("Then the phone company checks the line, and it gets stranger.", ["c5"], "s6"),
    ("The line to Room 12 was disconnected a full year before the call.", ["c5"], "s6"),
    ("And the street the caller named was a road torn out in 1961.", ["c6"], "s7"),
    ("The file is still open, and somewhere the line is still ringing.", ["c7"], "s8"),
    ("Because at 2:14 a.m., a call comes from a room that is empty.", ["c1"], "s1"),
]
SCRIPT = {
    "case_id": CASE["case_id"], "hook": _LINES[0][0],
    "lines": [{"text": t, "claim_ids": c, "shot_id": s} for t, c, s in _LINES],
    "shots": [
        {"id": "s1", "kind": "still", "prompt": "motel front desk at night, rotary phone",
         "template": "none", "move": "push_in", "mood": ["night", "phone"]},
        {"id": "s2", "kind": "scene3d", "prompt": "motel corridor", "template": "hallway",
         "move": "creep_forward", "mood": ["motel", "corridor"]},
        {"id": "s3", "kind": "still", "prompt": "empty rural road sign in fog",
         "template": "none", "move": "dolly_left", "mood": ["road", "fog"]},
        {"id": "s4", "kind": "scene3d", "prompt": "motel hallway, door 12",
         "template": "hallway", "move": "push_in", "mood": ["motel", "door"]},
        {"id": "s5", "kind": "scene3d", "prompt": "motel room, tv static", "template": "room",
         "move": "handheld_sway", "mood": ["room", "tv"]},
        {"id": "s6", "kind": "still", "prompt": "telephone exchange room, old switchboard",
         "template": "none", "move": "pull_out", "mood": ["phone"]},
        {"id": "s7", "kind": "scene3d", "prompt": "abandoned road at night",
         "template": "night_road", "move": "creep_forward", "mood": ["road", "night"]},
        {"id": "s8", "kind": "still", "prompt": "motel room telephone off the hook",
         "template": "none", "move": "push_in", "mood": ["phone", "room"]},
    ],
    "titles": ["TEST: The Room 12 Signal", "TEST: A call from an empty room",
               "TEST: The line was dead"],
    "description_summary": "Fictional test case used to check the pipeline.",
    "hashtags": ["#test"], "pinned_comment": "Test", "cover_text": "TEST CASE",
    "region_tag": "test", "sensitivity_notes": "fictional",
}

RESPONSES: dict[str, Any] = {
    "discover": {"candidates": [CASE]},
    "verify": FACT_PACK,
    "script": SCRIPT,
    "qa_fact": {"sentences": [{"sentence": t, "supported": True, "claim_ids": c,
                               "problem": ""} for t, c, _ in _LINES],
                "hook_strength": 8, "pacing": 8, "clarity": 8, "fix_instructions": ""},
    "qa_policy": {"passed": True, "violations": [], "fix_instructions": ""},
    "qa_visual": {"passed": True, "problems": []},
    "weekly_planning": {
        "insights": ["(offline) Hooks that open on a precise time hold viewers longest."],
        "case_mix": {"unsolved": 0.5, "solved_with_twist": 0.3, "strange_but_true": 0.2},
        "writer_notes": ["Keep the second line under ten words."],
    },
}


class OfflineLLM:
    """Duck-types `pipeline.llm.LLM.complete` for offline runs."""

    def __init__(self, governor: Governor) -> None:
        self.gov = governor
        self.settings: Settings = governor.settings
        self.calls: list[str] = []

    def complete(self, stage_name: str, prompt: str, *, system: str | None = None,
                 json_schema: dict[str, Any] | None = None, job_id: str | None = None,
                 urgent: bool = False, timeout_s: int = 900, add_dirs: Sequence[str] = (),
                 extra_tools: Sequence[str] = ()) -> LLMResult:
        self.calls.append(stage_name)
        t0 = time.monotonic()
        data = RESPONSES[stage_name]
        return LLMResult(text="", data=data, model="offline", input_tokens=0, output_tokens=0,
                         duration_s=time.monotonic() - t0)
