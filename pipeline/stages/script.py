"""Stage 3: write the short script + metadata from the fact pack, then lint it in code."""

from __future__ import annotations

import random
import re

from pipeline import prompts
from pipeline.llm import Completer
from pipeline.schemas import FactPack, Script

MIN_WORDS, MAX_WORDS = 110, 190


def word_count(script: Script) -> int:
    return sum(len(line.text.split()) for line in script.lines)


def lint(script: Script, pack: FactPack, min_words: int = MIN_WORDS,
         max_words: int = MAX_WORDS) -> list[str]:
    """Structural problems the writer must fix. Empty list = OK."""
    problems: list[str] = []
    ids = {c.id for c in pack.claims}
    shots = {s.id for s in script.shots}
    wc = word_count(script)
    if not min_words <= wc <= max_words:
        problems.append(f"script is {wc} words; must be {min_words}-{max_words}")
    for i, line in enumerate(script.lines):
        bad = set(line.claim_ids) - ids
        if bad:
            problems.append(f"line {i + 1} cites unknown claims {sorted(bad)}")
        if not line.claim_ids and i < len(script.lines) - 1:
            problems.append(f"line {i + 1} has no claim_ids (only the final CTA may)")
        if line.shot_id not in shots:
            problems.append(f"line {i + 1} points to unknown shot {line.shot_id}")
    problems += name_violations(script, pack)
    return problems


def name_violations(script: Script, pack: FactPack) -> list[str]:
    """Blocked names in the text. A blocked person's surname alone only counts if no allowed
    person shares it (family members usually share the victim's surname)."""
    text = " " + re.sub(r"[^a-z0-9' ]", " ", (" ".join(ln.text for ln in script.lines) + " "
                                              + " ".join(script.titles)).lower()) + " "
    allowed_parts = {w.lower() for p in pack.people if p.name_allowed for w in p.name.split()}
    out: list[str] = []
    for p in pack.people:
        if p.name_allowed:
            continue
        full = re.sub(r"[^a-z0-9' ]", " ", p.name.lower()).strip()
        parts = full.split()
        candidates = [full] + [w for w in parts if len(w) > 3 and w not in allowed_parts]
        for c in candidates:
            if c and f" {c} " in text:
                out.append(f"uses a name that is not allowed: {c}")
                break
    return out


def normalize(script: Script) -> Script:
    """Fix trivial structural drift instead of burning a rewrite on it."""
    if script.lines and script.hook.strip() != script.lines[0].text.strip():
        script = script.model_copy(update={"hook": script.lines[0].text.strip()})
    return script


def write_script(llm: Completer, pack: FactPack, *, feedback: str = "", job_id: str | None = None,
                 urgent: bool = False, hook_style: str = "impossible_fact",
                 cta: str | None = None, style_notes: list[str] | None = None,
                 previous: Script | None = None) -> Script:
    from pipeline.strategy import HOOK_STYLES

    if cta is None:
        ctas = [c for c in llm.settings.strategy.get("cta_variants", []) if c] or [""]
        cta = random.choice(ctas)
    notes = ""
    if style_notes:
        notes = ("\nStyle notes from recent performance (never override the hard rules):\n"
                 + "\n".join(f"- {n}" for n in style_notes[:5]))
    prompt = prompts.load(
        "script", voice_guide=prompts.voice_guide(), cta=cta or "(no CTA)",
        hook_instruction=HOOK_STYLES.get(hook_style, HOOK_STYLES["impossible_fact"]),
        style_notes=notes,
        feedback=f"\nFix these problems from the last draft:\n{feedback}" if feedback else "",
        previous_draft=(
            "\n\nRevise this previous draft. Change only what the problems above require and "
            "keep everything else as it is:\n" + previous.model_dump_json(indent=1)
        ) if previous is not None else "",
        fact_pack=pack.model_dump_json(indent=1),
    )
    res = llm.complete("script", prompt, json_schema=Script.json_schema(), job_id=job_id,
                       urgent=urgent)
    script = normalize(Script.model_validate(res.data))
    return script.model_copy(update={"case_id": pack.case_id})
