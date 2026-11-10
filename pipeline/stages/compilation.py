"""Stage 11: the Sunday long-form compilation (GOD_PROMPT §2 Stage 11).

Cold open (the week's 3 strongest hooks) → one 2–3 min chapter per case (expanded from
the fact pack, re-fact-checked; falls back to the short's own script if the expansion
fails) → outro. 1920x1080 at 24 fps. Chapters in the description, custom thumbnail,
"Weekly Case Archive" playlist, scheduled for Sunday noon ET.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pipeline import brand_art, prompts
from pipeline.config import Settings, pipeline_enabled
from pipeline.jobs import JOBS_DIR, Job
from pipeline.llm import Completer
from pipeline.media import duration, ffmpeg
from pipeline.schemas import Check, FactPack, Line, QAReport, Script, Shot
from pipeline.stages import qa, script, voice
from pipeline.stages.render import render_video
from pipeline.state import State
from pipeline.youtube import YouTube

log = logging.getLogger("acw")
SIZE, FPS = (640, 360), 24
MIN_CASES, MAX_CASES = 3, 8
CH_MIN_WORDS, CH_MAX_WORDS = 280, 500


@dataclass
class Piece:
    name: str
    title: str
    script: Script
    stills: Path
    card: tuple[str, str, str]


def select_jobs(state: State, now: datetime, jobs_dir: Path = JOBS_DIR,
                max_cases: int = MAX_CASES) -> list[Job]:
    since = (now - timedelta(days=7)).isoformat(timespec="seconds")
    rows = state.conn.execute(
        "SELECT job_id, meta FROM jobs WHERE kind='short' AND status='done' AND updated_at >= ?",
        (since,)).fetchall()
    scored = []
    for job_id, meta in rows:
        d = jobs_dir / job_id
        if (d / "script.json").exists() and (d / "fact_pack.json").exists():
            scored.append((float(json.loads(meta).get("quality", 0)), job_id))
    best = sorted(scored, reverse=True)[:max_cases]
    return [Job(j, jobs_dir) for _, j in sorted(best, key=lambda x: x[1])]


def _scene_shots(n: int) -> list[Shot]:
    plan = [("hallway", "creep_forward"), ("room", "handheld_sway"),
            ("night_road", "creep_forward"), ("hallway", "push_in"), ("room", "push_in")]
    return [Shot(id=f"x{i}", kind="scene3d", prompt=t, template=t, move=m, mood=[])  # type: ignore[arg-type]
            for i, (t, m) in enumerate(plan[:n])]


def cold_open(hooks: list[tuple[str, list[str]]], week_no: int) -> Script:
    shots = _scene_shots(4)
    lines = [Line(text=f"Week {week_no}. The archive recovered {len(hooks)} new files.",
                  claim_ids=[], shot_id="x0")]
    lines += [Line(text=t, claim_ids=c, shot_id=shots[(i + 1) % 4].id)
              for i, (t, c) in enumerate(hooks[:3])]
    lines.append(Line(text="Insert the first disc.", claim_ids=[], shot_id="x3"))
    return Script(case_id="cold-open", hook=lines[0].text, lines=lines, shots=shots,
                  titles=["Cold open", "Cold open", "Cold open"], description_summary="",
                  hashtags=[], pinned_comment="", cover_text="", region_tag="",
                  sensitivity_notes="")


def outro() -> Script:
    shots = _scene_shots(4)
    texts = ["That's everything recovered this week.",
             "Every case in this archive is real.",
             "If you know something, the contacts are in the description.",
             "A new file every eight hours. The archive opens again next Sunday.",
             "Insert the next disc."]
    lines = [Line(text=t, claim_ids=[], shot_id=shots[i % 4].id) for i, t in enumerate(texts)]
    return Script(case_id="outro", hook=texts[0], lines=lines, shots=shots,
                  titles=["Outro", "Outro", "Outro"], description_summary="", hashtags=[],
                  pinned_comment="", cover_text="", region_tag="", sensitivity_notes="")


def write_chapter(llm: Completer, job: Job, *, reuse: bool, urgent: bool = True) -> Script:
    short = job.load("script.json", Script)
    pack = job.load("fact_pack.json", FactPack)
    if reuse:
        return short
    feedback = ""
    for _ in range(2):
        res = llm.complete("compilation_script", prompts.load(
            "compilation", voice_guide=prompts.voice_guide(),
            short_script=qa.script_text(short) + feedback,
            fact_pack=pack.model_dump_json(indent=1)),
            json_schema=Script.json_schema(), job_id=f"weekly:{job.id}", urgent=urgent)
        ch = Script.model_validate(res.data).model_copy(update={"case_id": pack.case_id})
        problems = script.lint(ch, pack, CH_MIN_WORDS, CH_MAX_WORDS)
        problems = [p for p in problems if "hook must equal" not in p]
        if problems:
            feedback = "\n\nFix: " + "; ".join(problems)
            continue
        chk, _, fix = qa.fact_gate(llm, pack, ch, job_id=f"weekly:{job.id}", urgent=urgent)
        if chk.passed:
            return ch
        feedback = f"\n\nFix: {fix}"
    log.info("chapter for %s fell back to the short script", job.id)
    return short


def _fmt(t: float) -> str:
    s = int(t)
    if s >= 3600:
        return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


def build(llm: Completer, state: State, settings: Settings, week_job: Job, *,
          now: datetime | None = None, offline: bool = False,
          jobs_dir: Path = JOBS_DIR, reuse: bool | None = None) -> tuple[Path, dict[str, Any]]:
    now = now or datetime.now(UTC)
    jobs = select_jobs(state, now, jobs_dir)
    if len(jobs) < MIN_CASES:
        raise RuntimeError(f"only {len(jobs)} finished shorts this week; need {MIN_CASES}")
    from pipeline.budget import Governor

    if reuse is None:
        reuse = Governor(state, settings).is_degraded("compilation_reuse_narration")
    week_no = now.astimezone(ZoneInfo(settings.schedule.timezone)).isocalendar().week
    pieces: list[Piece] = []
    hooks: list[tuple[str, list[str]]] = []
    for j in jobs:
        sc = j.load("script.json", Script)
        pack = j.load("fact_pack.json", FactPack)
        row = state.get_job(j.id)
        case_no = json.loads(row["meta"]).get("case_no", "CASE") if row else "CASE"
        hooks.append((sc.hook, sc.lines[0].claim_ids))
        ch = write_chapter(llm, j, reuse=reuse)
        pieces.append(Piece(j.id, f"{case_no}: {sc.titles[0]}", ch, j.path("stills"),
                            (case_no, pack.location, str(pack.year))))
    pieces.insert(0, Piece("cold_open", "Cold open", cold_open(hooks, week_no),
                           week_job.path("none"), ("WEEKLY ARCHIVE", f"WEEK {week_no}", "")))
    pieces.append(Piece("outro", "Next week", outro(), week_job.path("none"),
                        ("END OF FILE", "", "")))

    parts: list[Path] = []
    chapters: list[tuple[float, str]] = []
    t = 0.0
    for k, p in enumerate(pieces):
        d = week_job.path(p.name)
        d.mkdir(parents=True, exist_ok=True)
        out = d / "part.mp4"
        if not out.exists():
            wav, timings = voice.narrate(p.script, d, settings.voice, offline=offline)
            render_video(p.script, timings, wav, p.stills, out, case_no=p.card[0],
                         location=p.card[1], year=p.card[2], style=settings.style,
                         size=SIZE, fps=FPS, caption_y=0.82, card_s=4.0, stamp_on=False,
                         seed=100 + k)
        chapters.append((t, p.title))
        t += duration(out)
        parts.append(out)
    listing = week_job.path("parts.txt")
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    final = week_job.path("compilation.mp4")
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
           "-movflags", "+faststart", str(final))
    title = f"Cold Case Archive, Week {week_no}: {len(jobs)} Unsolved and Strange Real Cases"
    thumb = week_job.path("thumbnail.png")
    brand_art.thumbnail_template(f"{len(jobs)} Cases Nobody Solved", f"WEEK {week_no} ARCHIVE",
                                 seed=week_no).save(thumb)
    meta = {"title": title[:100], "week": week_no, "seconds": round(t, 1),
            "midroll_eligible": t >= 8 * 60,
            "chapters": [(_fmt(s), name) for s, name in chapters],
            "jobs": [j.id for j in jobs]}
    week_job.save_json("compilation_meta.json", meta)
    return final, meta


def description(meta: dict[str, Any], packs: list[FactPack]) -> str:
    ch = "\n".join(f"{ts} {name}" for ts, name in meta["chapters"])
    srcs = []
    for p in packs:
        for c in p.claims:
            for x in c.citations:
                if x.url not in srcs:
                    srcs.append(x.url)
    return (f"This week's recovered case files, expanded.\n\n{ch}\n\nSources:\n"
            + "\n".join(f"• {u}" for u in srcs[:25])
            + "\n\nIf you have information about any case, contact the agency named in its "
              "chapter or NamUs (namus.nij.ojp.gov).\n\n#coldcase #unsolved #truecrime\n"
              "AI-assisted visuals and narration. Real cases, researched from public sources.")


def qa_compilation(llm: Completer, video: Path, week_job: Job) -> QAReport:
    checks: list[Check] = qa.technical_checks(video, None, size=(1920, 1080), fps="24/1",
                                              min_s=3 * 60, max_s=40 * 60)
    frames = qa.sample_frames(video, week_job.path("qa_frames"), n=8)
    checks.append(qa.visual_gate(llm, frames, job_id=week_job.id, urgent=True))
    report = QAReport(job_id=week_job.id, checks=checks, quality_score=0)
    week_job.save("qa.json", report)
    return report


def publish_slot(day: date, settings: Settings) -> datetime:
    """Next compilation slot on/after `day` (Sunday at schedule.compilation.time ET)."""
    tz = ZoneInfo(settings.schedule.timezone)
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    target = days.index(settings.schedule.compilation.day)
    d = day + timedelta(days=(target - day.weekday()) % 7)
    hh, mm = (int(x) for x in settings.schedule.compilation.time.split(":"))
    return datetime.combine(d, time(hh, mm), tzinfo=tz)


def publish(video: Path, meta: dict[str, Any], week_job: Job, settings: Settings,
            slot: datetime, *, live: bool, yt: YouTube | None,
            jobs_dir: Path = JOBS_DIR) -> dict[str, Any]:
    packs = [Job(j, jobs_dir).load("fact_pack.json", FactPack) for j in meta["jobs"]]
    snippet = {"title": meta["title"], "description": description(meta, packs)[:4900],
               "tags": ["cold case", "unsolved mysteries", "true crime", "compilation",
                        "case files", "missing persons"],
               "categoryId": str(settings.strategy.get("category_id", 24)),
               "defaultLanguage": "en", "defaultAudioLanguage": "en"}
    status = {"privacyStatus": "private",
              "publishAt": slot.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True,
              "embeddable": True, "license": "youtube"}
    if not (live and pipeline_enabled()) or yt is None:
        plan = {"snippet": snippet, "status": status, "dry_run": True}
        week_job.save_json("publish_plan.json", plan)
        return plan
    vid = yt.upload_video(video, snippet, status)
    result: dict[str, Any] = {"video_id": vid, "publish_at": status["publishAt"]}
    try:
        yt.set_thumbnail(vid, week_job.path("thumbnail.png"))
    except Exception as e:  # noqa: BLE001 - unverified channels can't set thumbnails
        result["thumbnail_error"] = str(e)[:200]
    from pipeline.stages.publish import playlist_ids

    pl = playlist_ids().get("Weekly Case Archive")
    if pl:
        yt.add_to_playlist(pl, vid)
    week_job.save_json("publish_result.json", result)
    return result
