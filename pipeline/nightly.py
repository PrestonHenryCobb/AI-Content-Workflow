"""The nightly run and the healthcheck (Phase 5 automation)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pipeline import alerts
from pipeline.budget import BudgetExceeded, Governor, SubscriptionLimited
from pipeline.config import Settings, load_settings, pipeline_enabled
from pipeline.run import make_short
from pipeline.stages import publish
from pipeline.state import State
from pipeline.youtube import Credentials, YouTube

log = logging.getLogger("acw")


@dataclass
class NightReport:
    produced: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    stopped_by: str = ""
    published: list[publish.Outcome] = field(default_factory=list)


def target_count(state: State, settings: Settings) -> int:
    """Shorts to make tonight: today's slots plus whatever refills the buffer to target."""
    per_day = settings.schedule.shorts_per_day
    gov = Governor(state, settings)
    if gov.is_degraded("shorts_per_day_3_to_2"):
        per_day = min(per_day, 2)
    have = len(state.buffer_available())
    return max(0, per_day + settings.schedule.buffer.target - have)


def run_night(state: State | None = None, settings: Settings | None = None, *,
              offline: bool = False, live: bool = True, max_jobs: int | None = None,
              today: date | None = None) -> NightReport:
    settings = settings or load_settings()
    state = state or State()
    tz = ZoneInfo(settings.schedule.timezone)
    today = today or datetime.now(tz).date()
    rep = NightReport()
    want = target_count(state, settings) if max_jobs is None else max_jobs
    attempts = 0
    while len(rep.produced) < want and attempts < want + 3:
        attempts += 1
        job_id = f"{today.isoformat()}-{attempts:02d}"
        try:
            res = make_short(job_id, offline=offline, urgent=offline, state=state,
                             settings=settings)
            (rep.produced if res.report and res.report.passed else rep.failed).append(job_id)
        except (SubscriptionLimited, BudgetExceeded) as e:
            rep.stopped_by = str(e)
            break
        except Exception as e:  # noqa: BLE001 - one bad job must not end the night
            log.exception("job %s crashed", job_id)
            rep.failed.append(f"{job_id}: {e}")
    yt = None
    really = live and pipeline_enabled()
    if really:
        yt = YouTube(Credentials.from_env(), Governor(state, settings))
    rep.published = publish.publish_day(state, settings, today, live=really, yt=yt)
    empty = [o for o in rep.published if o.status in ("empty", "failed")]
    if empty:
        alerts.notify(f"Slots not filled on {today}",
                      "\n".join(f"- {o.slot.isoformat()}: {o.status} {o.detail}" for o in empty))
    if len(state.buffer_available()) < settings.schedule.buffer.minimum_before_alert:
        alerts.notify("Buffer low", f"Only {len(state.buffer_available())} spare videos. "
                      f"Stopped by: {rep.stopped_by or 'n/a'}. Failures: {rep.failed[:5]}")
    return rep


def healthcheck(state: State | None = None, settings: Settings | None = None, *,
                now: datetime | None = None, live: bool = True) -> list[publish.Outcome]:
    """Fill any open slot in the next 12 h from the buffer (no production, cheap)."""
    settings = settings or load_settings()
    state = state or State()
    now = now or datetime.now(UTC)
    tz = ZoneInfo(settings.schedule.timezone)
    days = sorted({now.astimezone(tz).date(), (now + timedelta(hours=12)).astimezone(tz).date()})
    really = live and pipeline_enabled()
    yt = YouTube(Credentials.from_env(), Governor(state, settings)) if really else None
    out: list[publish.Outcome] = []
    for d in days:
        soon = [s for s in publish.open_slots(state, d, settings, now)
                if s - now <= timedelta(hours=12)]
        if soon:
            out += [o for o in publish.publish_day(state, settings, d, live=really, yt=yt, now=now)
                    if o.slot in soon]
    missing = [o for o in out if o.status == "empty"]
    if missing:
        alerts.notify("Slot about to go empty",
                      "\n".join(f"- {o.slot.isoformat()}: no video in the buffer" for o in missing))
    return out
