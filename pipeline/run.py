"""Orchestrates one short end to end (Stages 1–7). Publishing is Phase 4.

Each stage writes an artifact to data/jobs/<job_id>/ and is skipped if it already exists,
so a crashed or rate-limited run resumes where it stopped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

from pipeline import growth
from pipeline.budget import Governor
from pipeline.config import Settings, load_settings
from pipeline.jobs import Job
from pipeline.llm import LLM, Completer
from pipeline.offline import OfflineLLM
from pipeline.schemas import CaseCandidate, Check, FactPack, QAReport, Script
from pipeline.stages import art, discover, qa, render, script, verify, voice
from pipeline.state import JobStatus, Stage, State

log = logging.getLogger("acw")
MAX_REWRITES = 3


@dataclass
class Result:
    job: Job
    report: QAReport | None
    video: str | None


def _case_no(state: State, job_id: str) -> str:
    row = state.get_job(job_id)
    if row is not None:
        import json

        meta = json.loads(row["meta"])
        if "case_no" in meta:
            return str(meta["case_no"])
    n = state.conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'short'").fetchone()[0]
    return f"CASE #{int(n) + 1:04d}"


def script_with_gates(llm: Completer, pack: FactPack, *, job_id: str, urgent: bool,
                      hook_style: str, cta: str, notes: list[str],
                      max_rewrites: int = MAX_REWRITES) -> tuple[Script, list[Check], float] | str:
    """Write, lint, fact-check, policy-check; revise the *previous draft* on failure.

    Returns (script, checks, quality) or the last feedback string if every attempt failed.
    The policy gate only runs once the fact gate passes, to save Pro usage.
    """
    feedback = ""
    previous: Script | None = None
    for attempt in range(max_rewrites + 1):
        sc = script.write_script(llm, pack, feedback=feedback, job_id=job_id, urgent=urgent,
                                 hook_style=hook_style, cta=cta, style_notes=notes,
                                 previous=previous)
        previous = sc
        problems = script.lint(sc, pack)
        if problems:
            feedback = "\n".join(problems)
            log.info("script attempt %d failed lint: %s", attempt + 1, feedback)
            continue
        fact_chk, quality, fact_fix = qa.fact_gate(llm, pack, sc, job_id=job_id, urgent=urgent)
        if not fact_chk.passed:
            feedback = fact_fix
            log.info("script attempt %d failed fact check: %s", attempt + 1, feedback)
            continue
        pol_chk, pol_fix = qa.policy_gate(llm, pack, sc, job_id=job_id, urgent=urgent)
        if pol_chk.passed:
            return sc, [Check(name="script_lint", passed=True, detail="ok"), fact_chk,
                        pol_chk], quality
        feedback = pol_fix
        log.info("script attempt %d failed policy: %s", attempt + 1, feedback)
    return feedback


def make_short(job_id: str, *, case_hint: str = "", offline: bool = False,
               urgent: bool = False, state: State | None = None,
               settings: Settings | None = None) -> Result:
    settings = settings or load_settings()
    state = state or State()
    gov = Governor(state, settings)
    llm: Completer = OfflineLLM(gov) if offline else LLM(gov)
    job = Job(job_id)
    case_no = _case_no(state, job_id)
    meta: dict[str, Any] = {"case_no": case_no, "offline": offline}

    def mark(stage: Stage, status: JobStatus, error: str | None = None,
             case_id: str | None = None) -> None:
        state.upsert_job(job_id, "short", stage, status, case_id=case_id, error=error, meta=meta)


    # 1. discover
    if not job.has("case.json"):
        mark(Stage.DISCOVER, JobStatus.RUNNING)
        cand = discover.next_case(state)
        if cand is None or case_hint:
            found = discover.discover(llm, state, count=5, hint=case_hint,
                                       job_id=job_id, urgent=urgent)
            if not found:
                log.info("discover: no eligible, non-duplicate cases returned")
                mark(Stage.DISCOVER, JobStatus.FAILED, "no eligible cases")
                return Result(job, None, None)
            cand = found[0]
        job.save("case.json", cand)
    case = job.load("case.json", CaseCandidate)

    # 2. verify
    if not job.has("fact_pack.json"):
        mark(Stage.VERIFY, JobStatus.RUNNING, case_id=case.case_id)
        try:
            pack = verify.verify(llm, case, job_id=job_id, urgent=urgent)
        except verify.CaseBlocked as e:
            log.info("verify: case blocked: %s", e)
            with state.tx() as c:
                c.execute("UPDATE cases SET status = 'blocked' WHERE case_id = ?",
                          (case.case_id,))
            job.path("case.json").unlink()
            mark(Stage.VERIFY, JobStatus.FAILED, f"blocked: {e}")
            return Result(job, None, None)
        job.save("fact_pack.json", pack)
    pack = job.load("fact_pack.json", FactPack)

    # 3. script + text gates (before any render time is spent)
    checks: list[Check] = []
    if not job.has("script.json"):
        mark(Stage.SCRIPT, JobStatus.RUNNING, case_id=case.case_id)
        from pipeline import strategy

        hook_style = strategy.choose(state, "hook_style", list(strategy.HOOK_STYLES))
        ctas = [str(c) for c in settings.strategy.get("cta_variants", [""])]
        cta = strategy.choose(state, "cta", ctas)
        strategy.record_arm(state, job_id, "hook_style", hook_style)
        strategy.record_arm(state, job_id, "cta", cta)
        notes = [str(n) for n in strategy.get(state, "writer_notes", [])]
        meta.update({"hook_style": hook_style, "cta": cta})
        outcome = script_with_gates(llm, pack, job_id=job_id, urgent=urgent,
                                    hook_style=hook_style, cta=cta, notes=notes)
        if isinstance(outcome, str):
            mark(Stage.SCRIPT, JobStatus.DISCARDED, f"script failed gates: {outcome[:300]}")
            return Result(job, None, None)
        sc, checks, quality = outcome
        meta["quality"] = round(quality, 2)
        job.save("script.json", sc)
        job.save_json("text_checks.json", [c.model_dump() for c in checks])
    else:
        checks = [Check.model_validate(c)
                  for c in cast(list[dict[str, Any]], job.load_json("text_checks.json"))]
    sc = job.load("script.json", Script)

    # 4. voice
    if not job.has("timings.json"):
        mark(Stage.VOICE, JobStatus.RUNNING, case_id=case.case_id)
        _, timings = voice.narrate(sc, job.dir, settings.voice, offline=offline)
        job.save_json("timings.json", voice.timings_to_json(timings))
    timings = voice.timings_from_json(cast(list[dict[str, Any]], job.load_json("timings.json")))

    # 5. art
    mark(Stage.ART, JobStatus.RUNNING, case_id=case.case_id)
    sources = art.make_stills(sc, job.path("stills"), gov, settings.style,
                              settings.models.images.usd_per_image, offline=offline)
    job.save_json("art_sources.json", sources)

    # 6. render
    video = job.path("short.mp4")
    if not video.exists():
        mark(Stage.RENDER, JobStatus.RUNNING, case_id=case.case_id)
        render.render_short(sc, timings, job.path("narration.wav"), job.path("stills"), video,
                            case_no=case_no, location=pack.location, year=pack.year,
                            style=settings.style, segment=growth.segment_for(case.category),
                            depth_model=str(settings.animation.parallax.get("depth_model_runtime",
                                                                             "heuristic")))

    # 7. technical + visual QA
    mark(Stage.QA, JobStatus.RUNNING, case_id=case.case_id)
    checks = [c for c in checks if c.name in ("script_lint", "fact", "policy")]
    checks += qa.technical_checks(video, job.path("narration.wav"))
    frames = qa.sample_frames(video, job.path("qa_frames"))
    checks.append(qa.visual_gate(llm, frames, job_id=job_id, urgent=urgent))
    report = QAReport(job_id=job_id, checks=checks, quality_score=float(meta.get("quality", 0)))
    job.save("qa.json", report)
    if report.passed:
        mark(Stage.QA, JobStatus.DONE, case_id=case.case_id)
        state.add_to_buffer(job_id)
        with state.tx() as c:
            c.execute("UPDATE cases SET status = 'verified' WHERE case_id = ?", (case.case_id,))
    else:
        failed = ", ".join(c.name for c in report.checks if not c.passed)
        mark(Stage.QA, JobStatus.FAILED, f"QA failed: {failed}", case_id=case.case_id)
    return Result(job, report, str(video))
