"""`acw` command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from pipeline.budget import Governor
from pipeline.config import load_settings, pipeline_enabled
from pipeline.state import State


def cmd_check_config(_: argparse.Namespace) -> int:
    s = load_settings()
    print(f"config OK: {s.schedule.shorts_per_day} shorts/day, "
          f"${s.budget.global_weekly_usd:.2f}/week cap, tz={s.schedule.timezone}")
    return 0


def cmd_init_db(_: argparse.Namespace) -> int:
    State().close()
    print("state DB ready")
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    state = State()
    st = Governor(state).status()
    out = {
        "week_start": st.week_start.isoformat(),
        "spent_total": round(st.spent_total, 4),
        "spent_by_provider": {k: round(v, 4) for k, v in st.spent_by_provider.items()},
        "global_cap": st.global_cap,
        "remaining": round(st.remaining, 4),
        "daily_allowance": round(st.daily_allowance, 4),
        "projected_total": round(st.projected_total, 4),
        "active_degradations": st.active_degradations,
        "claude_calls_today": f"{st.subscription.calls_today}/{st.subscription.daily_cap}",
        "claude_calls_week": f"{st.subscription.calls_week}/{st.subscription.weekly_cap}",
        "claude_limit_hits": st.subscription.limit_hits_week,
        "claude_cooldown_until": (st.subscription.cooldown_until.isoformat()
                                  if st.subscription.cooldown_until else None),
        "in_run_window": st.subscription.in_run_window,
    }
    print(json.dumps(out, indent=2) if args.json else
          "\n".join(f"{k:20} {v}" for k, v in out.items()))
    state.close()
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    state = State()
    s = load_settings()
    buffered = len(state.buffer_available())
    print(f"pipeline_enabled     {pipeline_enabled()}")
    print(f"buffer               {buffered}/{s.schedule.buffer.target}")
    print(f"youtube_quota_left   {Governor(state, s).youtube_quota_left()}")
    state.close()
    return 0


def cmd_make_short(args: argparse.Namespace) -> int:
    import logging

    from pipeline.run import make_short

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    res = make_short(args.job_id, case_hint=args.case, offline=args.offline, urgent=args.urgent)
    if res.report is None:
        print(f"job {args.job_id}: stopped before QA (see `acw status` / state DB)")
        return 1
    for c in res.report.checks:
        print(f"{'PASS' if c.passed else 'FAIL'}  {c.name:14} {c.detail}")
    print(f"video: {res.video}")
    return 0 if res.report.passed else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="acw", description="AI-Content-Workflow pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-config", help="validate config/*.yaml").set_defaults(fn=cmd_check_config)
    sub.add_parser("init-db", help="create data/state.db").set_defaults(fn=cmd_init_db)
    b = sub.add_parser("budget", help="this week's spend vs. caps")
    b.add_argument("--json", action="store_true")
    b.set_defaults(fn=cmd_budget)
    sub.add_parser("status", help="kill switch, buffer, quota").set_defaults(fn=cmd_status)
    m = sub.add_parser("make-short", help="produce one short end to end (no upload)")
    m.add_argument("--job-id", required=True)
    m.add_argument("--case", default="", help="optional hint: a specific case or theme")
    m.add_argument("--offline", action="store_true",
                   help="fictional fixture case, silent voice, procedural art; no network")
    m.add_argument("--urgent", action="store_true",
                   help="allow Claude calls outside the overnight window")
    m.set_defaults(fn=cmd_make_short)
    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
