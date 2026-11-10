"""Typed artifacts passed between stages. Each is saved as JSON in the job folder.

The same models generate the JSON Schemas handed to `claude -p --json-schema`, so the
model's output is validated against exactly what the code expects.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        return cls.model_json_schema()


# ---------- Stage 1: discover ----------
class CaseScores(_M):
    intrigue: int = Field(ge=1, le=10)
    novelty: int = Field(ge=1, le=10)
    visual: int = Field(ge=1, le=10)
    source_quality: int = Field(ge=1, le=10)
    risk: int = Field(ge=1, le=10, description="10 = highest legal/ethical risk")


class CaseCandidate(_M):
    case_id: str = Field(description="kebab-case slug: surname-or-place-year")
    title: str
    summary: str
    location: str
    year: int
    category: Literal["unsolved", "solved_with_twist", "strange_but_true"]
    sources: list[str] = Field(min_length=1)
    scores: CaseScores
    risk_notes: str


class Candidates(_M):
    candidates: list[CaseCandidate]


# ---------- Stage 2: verify ----------
class Citation(_M):
    url: str
    quote: str = Field(description="short verbatim excerpt supporting the claim")


class Claim(_M):
    id: str = Field(description="c1, c2, ...")
    text: str
    citations: list[Citation] = Field(min_length=1)


class Person(_M):
    role: Literal["victim", "missing_person", "convicted", "charged_pending",
                  "acquitted", "uncharged_person_of_interest", "investigator",
                  "family", "witness", "other"]
    name: str
    is_minor: bool = False
    name_allowed: bool = Field(description="false for uncharged people, minors, family")


class FactPack(_M):
    case_id: str
    title: str
    location: str
    year: int
    legal_status: Literal["open", "closed", "convicted", "acquitted",
                          "suspect_named_uncharged"]
    active_trial: bool
    people: list[Person]
    claims: list[Claim] = Field(min_length=6)
    agency_contact: str = Field(description="who to contact with information, or 'n/a'")
    sources: list[str]


# ---------- Stage 3: script ----------
class Shot(_M):
    id: str = Field(description="s1, s2, ...")
    kind: Literal["still", "scene3d"]
    prompt: str = Field(description="visual description: place, era, weather, objects; "
                        "no real faces, no gore, no text")
    template: Literal["hallway", "night_road", "room", "none"] = "none"
    move: Literal["push_in", "pull_out", "dolly_left", "dolly_right", "handheld_sway",
                  "creep_forward"] = "push_in"
    mood: list[str] = Field(default_factory=list, description="tags for clip-library reuse")


class Line(_M):
    text: str
    claim_ids: list[str] = Field(description="fact-pack claims this sentence relies on; "
                                 "empty only for the CTA")
    shot_id: str


class Script(_M):
    case_id: str
    hook: str = Field(description="first line, also lines[0].text")
    lines: list[Line] = Field(min_length=5)
    shots: list[Shot] = Field(min_length=4, max_length=12)
    titles: list[str] = Field(min_length=3, max_length=5)
    description_summary: str
    hashtags: list[str]
    pinned_comment: str
    cover_text: str = Field(max_length=40)
    region_tag: str
    sensitivity_notes: str


# ---------- Stage 7: QA ----------
class SentenceCheck(_M):
    sentence: str
    supported: bool
    claim_ids: list[str]
    problem: str = ""


class FactVerdict(_M):
    sentences: list[SentenceCheck]
    hook_strength: int = Field(ge=1, le=10)
    pacing: int = Field(ge=1, le=10)
    clarity: int = Field(ge=1, le=10)
    fix_instructions: str = ""


class PolicyVerdict(_M):
    passed: bool
    violations: list[str]
    fix_instructions: str = ""


class VisualVerdict(_M):
    passed: bool
    problems: list[str]


class Check(_M):
    name: str
    passed: bool
    detail: str = ""


class QAReport(_M):
    job_id: str
    checks: list[Check]
    quality_score: float

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


# ---------- Stage 10: weekly planning ----------
class CaseMix(_M):
    unsolved: float = Field(ge=0.1, le=0.75)
    solved_with_twist: float = Field(ge=0.1, le=0.75)
    strange_but_true: float = Field(ge=0.1, le=0.75)


class WeeklyPlan(_M):
    insights: list[str] = Field(max_length=6)
    case_mix: CaseMix
    writer_notes: list[str] = Field(max_length=5)
