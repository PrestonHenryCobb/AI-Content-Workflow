"""Weekly owner digest (GOD_PROMPT §6): ≤5 things that matter, plus the numbers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pipeline.budget import Governor
from pipeline.config import Settings
from pipeline.state import State


def build(state: State, settings: Settings, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=7)).isoformat(timespec="seconds")
    gov = Governor(state, settings, now=now)
    st = gov.status()
    pubs = state.conn.execute(
        "SELECT status, COUNT(*) FROM publications WHERE created_at >= ? GROUP BY status",
        (since,)).fetchall() if _has(state, "publications") else []
    pub = dict(pubs)
    jobs = dict(state.conn.execute(
        "SELECT status, COUNT(*) FROM jobs WHERE updated_at >= ? GROUP BY status",
        (since,)).fetchall())
    failures = state.conn.execute(
        "SELECT job_id, error FROM jobs WHERE updated_at >= ? AND status IN "
        "('failed','discarded') ORDER BY updated_at DESC LIMIT 5", (since,)).fetchall()
    buffer = len(state.buffer_available())
    sub = st.subscription

    needs: list[str] = []
    if pub.get("failed"):
        needs.append(f"{pub['failed']} uploads failed: check the YouTube secrets / API audit.")
    if buffer < settings.schedule.buffer.minimum_before_alert:
        needs.append(f"Buffer is low ({buffer}). Production may be blocked; see failures below.")
    if sub.limit_hits_week:
        needs.append(f"Claude Pro limit hit {sub.limit_hits_week}× this week. If you were "
                     "locked out of your own Claude use, set shorts_per_day: 2.")
    if st.spent_total > st.global_cap * settings.budget.warn_at_fraction:
        needs.append(f"Spend is at ${st.spent_total:.2f} of ${st.global_cap:.2f}.")
    if not needs:
        needs.append("Nothing. It's running on its own.")

    lines = [
        f"## Cold Save weekly digest, week of {st.week_start.date()}",
        "",
        "### Needs you",
        *[f"- {n}" for n in needs[:5]],
        "",
        "### Numbers",
        f"- Shorts scheduled: **{pub.get('scheduled', 0)}** (dry runs: {pub.get('dry_run', 0)}, "
        f"failed: {pub.get('failed', 0)})",
        f"- Shorts produced: {jobs.get('done', 0)} passed QA, {jobs.get('failed', 0)} failed, "
        f"{jobs.get('discarded', 0)} discarded at script stage",
        f"- Buffer: {buffer}/{settings.schedule.buffer.target}",
        f"- Spend: ${st.spent_total:.2f} / ${st.global_cap:.2f}",
        f"- Claude calls: {sub.calls_week}/{sub.weekly_cap} (limit hits: {sub.limit_hits_week})",
        f"- Degradations active: {', '.join(st.active_degradations) or 'none'}",
    ]
    from pipeline.analytics import summary

    learned = summary(state)
    if learned["insights"]:
        lines += ["", "### What's working", *[f"- {i}" for i in learned["insights"]]]
    if learned["hook_styles"]:
        lines.append("- Hook styles (wins/losses): " + ", ".join(
            f"{k} {w}/{lo}" for k, (w, lo) in learned["hook_styles"].items()))
    if failures:
        lines += ["", "### Recent failures", *[f"- `{j}`: {e}" for j, e in failures]]
    return "\n".join(lines)


def _has(state: State, table: str) -> bool:
    row = state.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None
