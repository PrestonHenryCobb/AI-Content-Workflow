"""Stage 2: build the fact pack, then enforce hard gates in code (not just in the prompt)."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from pipeline import prompts
from pipeline.llm import Completer
from pipeline.schemas import CaseCandidate, FactPack

BANNED_SOURCE_HOSTS = ("reddit.com", "youtube.com", "youtu.be", "tiktok.com", "facebook.com",
                       "quora.com", "fandom.com")


class CaseBlocked(RuntimeError):
    """The case fails a hard safety/legal gate and must not be produced."""


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def sanitize(pack: FactPack, min_age_years: int = 10) -> FactPack:
    """Drop banned citations, drop claims left uncited, block unsafe cases."""
    if pack.active_trial:
        raise CaseBlocked(f"{pack.case_id}: active trial")
    if datetime.now(UTC).year - pack.year < min_age_years:
        raise CaseBlocked(f"{pack.case_id}: newer than {min_age_years} years")
    claims = []
    for c in pack.claims:
        cites = [x for x in c.citations if not _host(x.url).endswith(BANNED_SOURCE_HOSTS)]
        if cites:
            claims.append(c.model_copy(update={"citations": cites}))
    if len(claims) < 6:
        raise CaseBlocked(f"{pack.case_id}: only {len(claims)} usable claims")
    people = [p.model_copy(update={"name_allowed": False})
              if p.is_minor or p.role in ("uncharged_person_of_interest", "family")
              else p for p in pack.people]
    return pack.model_copy(update={"claims": claims, "people": people})


def independent_sources(pack: FactPack, claim_id: str) -> int:
    claim = next(c for c in pack.claims if c.id == claim_id)
    return len({_host(x.url) for x in claim.citations})


def verify(llm: Completer, case: CaseCandidate, *, job_id: str | None = None,
           urgent: bool = False) -> FactPack:
    prompt = prompts.load("verify", title=case.title, location=case.location, year=case.year,
                          sources="\n".join(case.sources))
    res = llm.complete("verify", prompt, json_schema=FactPack.json_schema(), job_id=job_id,
                       urgent=urgent, timeout_s=1500)
    pack = FactPack.model_validate(res.data)
    pack = pack.model_copy(update={"case_id": case.case_id})
    return sanitize(pack, int(llm.settings.sources.get("min_case_age_years", 10)))
