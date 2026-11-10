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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="acw", description="AI-Content-Workflow pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-config", help="validate config/*.yaml").set_defaults(fn=cmd_check_config)
    sub.add_parser("init-db", help="create data/state.db").set_defaults(fn=cmd_init_db)
    b = sub.add_parser("budget", help="this week's spend vs. caps")
    b.add_argument("--json", action="store_true")
    b.set_defaults(fn=cmd_budget)
    sub.add_parser("status", help="kill switch, buffer, quota").set_defaults(fn=cmd_status)
    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
