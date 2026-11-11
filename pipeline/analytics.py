"""Stages 9–10: pull per-video analytics, label outcomes, run the weekly planner."""

from __future__ import annotations

import statistics
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pipeline import prompts, strategy
from pipeline.config import Settings
from pipeline.llm import Completer
from pipeline.schemas import CaseMix, WeeklyPlan
from pipeline.state import State, now_iso
from pipeline.youtube import YouTube

ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
METRICS = "views,averageViewPercentage,averageViewDuration,likes,comments,subscribersGained"
MIN_AGE = timedelta(hours=48)       # YouTube Analytics lags ~2 days
MAX_AGE = timedelta(days=28)


def videos_to_fetch(state: State, now: datetime) -> list[tuple[str, str]]:
    rows = state.conn.execute(
        "SELECT video_id, job_id, slot FROM publications WHERE platform='youtube' "
        "AND status='scheduled' AND video_id IS NOT NULL").fetchall()
    out = []
    for vid, job, slot in rows:
        age = now - datetime.fromisoformat(slot)
        if MIN_AGE <= age <= MAX_AGE:
            out.append((vid, job))
    return out


def fetch(yt: YouTube, state: State, now: datetime | None = None) -> int:
    """Store latest lifetime metrics per video. Returns rows updated."""
    now = now or datetime.now(UTC)
    strategy.init(state)
    vids = videos_to_fetch(state, now)
    if not vids:
        return 0
    job_of = dict(vids)
    start = (now - MAX_AGE - timedelta(days=1)).date().isoformat()
    n = 0
    for i in range(0, len(vids), 50):
        batch = [v for v, _ in vids[i:i + 50]]
        url = (f"{ANALYTICS}?ids=channel==MINE&startDate={start}&endDate={now.date()}"
               f"&metrics={METRICS}&dimensions=video&filters=video=={','.join(batch)}")
        r = yt._call("analytics.query", "GET", url)
        for row in r.json().get("rows", []):
            vid, views, pct, dur, likes, comments, subs = row
            with state.tx() as c:
                c.execute(
                    "INSERT INTO video_stats (video_id, job_id, fetched_at, views, avg_view_pct, "
                    "avg_view_s, likes, comments, subs) VALUES (?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(video_id) DO UPDATE SET fetched_at=excluded.fetched_at, "
                    "views=excluded.views, avg_view_pct=excluded.avg_view_pct, "
                    "avg_view_s=excluded.avg_view_s, likes=excluded.likes, "
                    "comments=excluded.comments, subs=excluded.subs",
                    (vid, job_of.get(vid), now_iso(), views, pct, dur, likes, comments, subs))
            n += 1
    label(state)
    prune(state, now)
    return n


RETENTION = timedelta(days=30)


def prune(state: State, now: datetime) -> int:
    """YouTube API Services policy: stored API data must be refreshed or deleted within 30
    days. Fold old rows' outcomes into per-arm win/loss counts (no API data), then delete
    them. Returns rows deleted."""
    strategy.init(state)
    cutoff = (now - RETENTION).isoformat(timespec="seconds")
    with state.tx() as c:
        c.execute(
            "INSERT INTO arm_archive (name, value, wins, losses) "
            "SELECT a.name, a.value, SUM(v.success), SUM(1 - v.success) FROM arms a "
            "JOIN video_stats v ON v.job_id = a.job_id "
            "WHERE v.fetched_at < ? AND v.success IS NOT NULL GROUP BY a.name, a.value "
            "ON CONFLICT(name, value) DO UPDATE SET wins = wins + excluded.wins, "
            "losses = losses + excluded.losses", (cutoff,))
        cur = c.execute("DELETE FROM video_stats WHERE fetched_at < ?", (cutoff,))
        return int(cur.rowcount)


def label(state: State) -> None:
    """success = average % viewed at or above the median of all fetched videos."""
    strategy.init(state)
    pcts = [r[0] for r in state.conn.execute(
        "SELECT avg_view_pct FROM video_stats WHERE avg_view_pct IS NOT NULL")]
    if len(pcts) < 4:
        return
    med = statistics.median(pcts)
    with state.tx() as c:
        c.execute("UPDATE video_stats SET success = CASE WHEN avg_view_pct >= ? THEN 1 ELSE 0 END "
                  "WHERE avg_view_pct IS NOT NULL", (med,))


def stats_table(state: State, limit: int = 40) -> str:
    strategy.init(state)
    rows = state.conn.execute(
        "SELECT v.video_id, v.views, v.avg_view_pct, v.subs, p.title, "
        "(SELECT value FROM arms a WHERE a.job_id = v.job_id AND a.name='hook_style'), "
        "c.meta FROM video_stats v LEFT JOIN publications p ON p.video_id = v.video_id "
        "LEFT JOIN jobs j ON j.job_id = v.job_id LEFT JOIN cases c ON c.case_id = j.case_id "
        "ORDER BY v.fetched_at DESC LIMIT ?", (limit,)).fetchall()
    import json

    lines = ["views | avg% | subs | category | hook | title"]
    for _vid, views, pct, subs, title, hook, meta in rows:
        cat = json.loads(meta).get("category", "?") if meta else "?"
        lines.append(f"{views} | {pct:.0f} | {subs} | {cat} | {hook or '?'} | {title or '?'}")
    return "\n".join(lines)


def current_mix(state: State, settings: Settings) -> dict[str, float]:
    base = {k: float(v) for k, v in settings.sources.get("case_mix", {}).items()}
    override: dict[str, float] | None = strategy.get(state, "case_mix")
    return override or base


def plan_week(llm: Completer, state: State, settings: Settings, *,
              today: date | None = None, min_videos: int = 6) -> WeeklyPlan | None:
    strategy.init(state)
    n = state.conn.execute("SELECT COUNT(*) FROM video_stats").fetchone()[0]
    if n < min_videos:
        return None
    mix = current_mix(state, settings)
    res = llm.complete("weekly_planning", prompts.load(
        "weekly_planning", current_mix=mix, table=stats_table(state)),
        json_schema=WeeklyPlan.json_schema(), urgent=True)
    plan = WeeklyPlan.model_validate(res.data)
    new = clamp_mix(mix, plan.case_mix)
    strategy.put(state, "case_mix", new)
    strategy.put(state, "writer_notes", plan.writer_notes[:5])
    strategy.put(state, "insights", plan.insights[:6])
    strategy.put(state, "planned_on", (today or date.today()).isoformat())
    return plan


def clamp_mix(old: dict[str, float], proposed: CaseMix, step: float = 0.15) -> dict[str, float]:
    """Move at most `step` per key, keep within [0.1, 0.75], renormalize."""
    out: dict[str, float] = {}
    for k, v in proposed.model_dump().items():
        o = old.get(k, 1 / 3)
        out[k] = min(0.75, max(0.10, min(o + step, max(o - step, float(v)))))
    total = sum(out.values())
    return {k: round(v / total, 3) for k, v in out.items()}


def summary(state: State) -> dict[str, Any]:
    return {"insights": strategy.get(state, "insights", []),
            "writer_notes": strategy.get(state, "writer_notes", []),
            "case_mix": strategy.get(state, "case_mix"),
            "hook_styles": strategy.arm_stats(state, "hook_style")}
