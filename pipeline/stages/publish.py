"""Stage 8: schedule finished shorts into posting slots and upload them.

Videos are uploaded ahead of time as private with `publishAt`, so they go public at the
slot even if no job is running then. Nothing is uploaded unless BOTH the kill switch
(PIPELINE_ENABLED=true) and `live=True` are set; otherwise a publish plan is written.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from pipeline.config import REPO_ROOT, Settings, pipeline_enabled
from pipeline.jobs import JOBS_DIR, Job
from pipeline.schemas import CaseCandidate, FactPack, Script
from pipeline.state import State, now_iso
from pipeline.youtube import YouTube

BRAND = REPO_ROOT / "brand"
IDS_FILE = REPO_ROOT / "config" / "youtube_ids.json"
PUBLISHED = REPO_ROOT / "data" / "published_cases.json"
MIN_LEAD = timedelta(minutes=20)       # YouTube needs publishAt in the future

SCHEMA = """
CREATE TABLE IF NOT EXISTS publications (
    job_id      TEXT NOT NULL,
    platform    TEXT NOT NULL,
    slot        TEXT NOT NULL,             -- ISO datetime (UTC) the video goes public
    status      TEXT NOT NULL,             -- dry_run | scheduled | failed
    video_id    TEXT,
    title       TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (platform, slot)
);
"""

CATEGORY_PLAYLIST = {"unsolved": "Still Missing", "solved_with_twist": "Solved After Decades",
                     "strange_but_true": "Strange But True"}


@dataclass
class Plan:
    job_id: str
    slot: datetime
    title: str
    description: str
    tags: list[str]
    category_id: str
    playlists: list[str]
    pinned_comment: str

    def snippet(self) -> dict[str, Any]:
        return {"title": self.title, "description": self.description, "tags": self.tags,
                "categoryId": self.category_id, "defaultLanguage": "en",
                "defaultAudioLanguage": "en"}

    def status(self) -> dict[str, Any]:
        return {"privacyStatus": "private",
                "publishAt": self.slot.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True,
                "embeddable": True, "license": "youtube"}


def init(state: State) -> None:
    state.conn.executescript(SCHEMA)


# ----- slots -----
def slots_for(day: date, settings: Settings) -> list[datetime]:
    tz = ZoneInfo(settings.schedule.timezone)
    out = []
    for s in settings.schedule.slots[: settings.schedule.shorts_per_day]:
        hh, mm = (int(x) for x in s.split(":"))
        out.append(datetime.combine(day, time(hh, mm), tzinfo=tz))
    return out


def open_slots(state: State, day: date, settings: Settings, now: datetime) -> list[datetime]:
    init(state)
    taken = {r[0] for r in state.conn.execute(
        "SELECT slot FROM publications WHERE platform = 'youtube' AND status != 'failed'")}
    return [s for s in slots_for(day, settings)
            if s - now >= MIN_LEAD and s.astimezone(UTC).isoformat() not in taken]


# ----- choosing a video -----
def choose_job(state: State, jobs_dir: Path = JOBS_DIR,
               now: datetime | None = None) -> str | None:
    """Freshest video made in the last 24 h, else the oldest buffered one."""
    now = now or datetime.now(UTC)
    rows = state.conn.execute(
        "SELECT job_id, added_at FROM buffer WHERE used_at IS NULL ORDER BY added_at").fetchall()
    usable = [(j, a) for j, a in rows if (jobs_dir / j / "short.mp4").exists()]
    if not usable:
        return None
    fresh = [(j, a) for j, a in usable
             if now - datetime.fromisoformat(a) <= timedelta(hours=24)]
    return str((fresh[-1] if fresh else usable[0])[0])


# ----- metadata -----
def _template() -> str:
    text = (BRAND / "channel_description.md").read_text()
    section = text.split("## Per-video description template", 1)[1]
    m = re.search(r"```\n(.*?)```", section, re.S)
    if not m:
        raise ValueError("per-video description template not found")
    return m.group(1).strip()


def _sources(pack: FactPack, limit: int = 6) -> list[str]:
    seen: list[str] = []
    for c in pack.claims:
        for x in c.citations:
            if x.url not in seen:
                seen.append(x.url)
    return seen[:limit]


def _identity() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((BRAND / "identity.yaml").read_text())
    return data


def build_plan(job: Job, slot: datetime, settings: Settings, case_no: str) -> Plan:
    sc = job.load("script.json", Script)
    pack = job.load("fact_pack.json", FactPack)
    case = job.load("case.json", CaseCandidate)
    region = re.sub(r"[^a-z0-9]", "", sc.region_tag.lower()) or "truecrime"
    desc = (_template()
            .replace("{hook_line}", sc.hook)
            .replace("{case_no}", case_no.removeprefix("CASE #"))
            .replace("{location}", pack.location)
            .replace("{year}", str(pack.year))
            .replace("{two_sentence_summary}", sc.description_summary)
            .replace("{sources_bulleted}", "\n".join(f"• {u}" for u in _sources(pack)))
            .replace("{agency_contact}", pack.agency_contact)
            .replace("{region_tag}", region))
    extra = " ".join(h if h.startswith("#") else f"#{h}" for h in sc.hashtags[:3])
    if extra:
        desc += f"\n{extra}"
    keywords = [str(k) for k in _identity().get("keywords", [])]
    tags = list(dict.fromkeys([*keywords, pack.location.split(",")[0], str(pack.year)]))
    while sum(len(t) + 1 for t in tags) > 480:          # YouTube tag budget is 500 chars
        tags.pop()
    playlists = [CATEGORY_PLAYLIST[case.category], f"By Decade: {pack.year // 10 * 10}s"]
    return Plan(job_id=job.id, slot=slot, title=sc.titles[0][:100], description=desc[:4900],
                tags=tags, category_id=str(settings.strategy.get("category_id", 24)),
                playlists=playlists,
                pinned_comment=f"{case_no}: {sc.pinned_comment}"[:1000])


def _record_published(case_id: str, title: str, video_id: str | None, slot: datetime) -> None:
    try:
        data = json.loads(PUBLISHED.read_text())
    except FileNotFoundError:
        data = []
    data.append({"case_id": case_id, "title": title, "video_id": video_id,
                 "publish_at": slot.astimezone(UTC).isoformat()})
    PUBLISHED.write_text(json.dumps(data, indent=2))


def playlist_ids() -> dict[str, str]:
    try:
        return dict(json.loads(IDS_FILE.read_text()).get("playlists", {}))
    except FileNotFoundError:
        return {}


@dataclass
class Outcome:
    slot: datetime
    job_id: str | None
    status: str
    video_id: str | None = None
    detail: str = ""


def publish_day(state: State, settings: Settings, day: date, *, live: bool = False,
                yt: YouTube | None = None, now: datetime | None = None,
                jobs_dir: Path = JOBS_DIR) -> list[Outcome]:
    now = now or datetime.now(UTC)
    init(state)
    really = live and pipeline_enabled()
    if really and yt is None:
        raise RuntimeError("live publish needs a YouTube client")
    outcomes: list[Outcome] = []
    ids = playlist_ids()
    channel_id = json.loads(IDS_FILE.read_text()).get("channel_id") if IDS_FILE.exists() else None
    for slot in open_slots(state, day, settings, now):
        job_id = choose_job(state, jobs_dir, now)
        if job_id is None:
            outcomes.append(Outcome(slot, None, "empty", detail="no finished video available"))
            continue
        job = Job(job_id, jobs_dir)
        row = state.get_job(job_id)
        case_no = json.loads(row["meta"]).get("case_no", "CASE") if row else "CASE"
        plan = build_plan(job, slot, settings, case_no)
        slot_key = slot.astimezone(UTC).isoformat()
        if not really:
            job.save_json("publish_plan.json", {"snippet": plan.snippet(),
                                                "status": plan.status(),
                                                "playlists": plan.playlists,
                                                "comment": plan.pinned_comment})
            state.take_from_buffer(slot_key, job_id=job_id)
            _insert(state, job_id, slot_key, "dry_run", None, plan.title, None)
            outcomes.append(Outcome(slot, job_id, "dry_run", detail=plan.title))
            continue
        assert yt is not None
        try:
            vid = yt.upload_video(job.path("short.mp4"), plan.snippet(), plan.status())
            for name in plan.playlists:
                if name in ids:
                    yt.add_to_playlist(ids[name], vid)
            if channel_id:
                yt.comment(channel_id, vid, plan.pinned_comment)
            state.take_from_buffer(slot_key, job_id=job_id)
            _insert(state, job_id, slot_key, "scheduled", vid, plan.title, None)
            case = job.load("case.json", CaseCandidate)
            _record_published(case.case_id, case.title, vid, slot)
            with state.tx() as c:
                c.execute("UPDATE cases SET status='published', published_at=? WHERE case_id=?",
                          (now_iso(), case.case_id))
            outcomes.append(Outcome(slot, job_id, "scheduled", vid, plan.title))
        except Exception as e:  # noqa: BLE001 - one failed slot must not stop the others
            _insert(state, job_id, slot_key, "failed", None, plan.title, str(e)[:500])
            outcomes.append(Outcome(slot, job_id, "failed", detail=str(e)[:200]))
    return outcomes


def _insert(state: State, job_id: str, slot: str, status: str, video_id: str | None,
            title: str, error: str | None) -> None:
    with state.tx() as c:
        c.execute("INSERT OR REPLACE INTO publications (job_id, platform, slot, status, "
                  "video_id, title, error, created_at) VALUES (?,?,?,?,?,?,?,?)",
                  (job_id, "youtube", slot, status, video_id, title, error, now_iso()))
