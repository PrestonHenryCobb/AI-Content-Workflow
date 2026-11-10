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


def cmd_publish(args: argparse.Namespace) -> int:
    from datetime import date

    from pipeline.budget import Governor
    from pipeline.stages.publish import publish_day
    from pipeline.youtube import Credentials, YouTube

    settings = load_settings()
    state = State()
    day = date.fromisoformat(args.date) if args.date else date.today()
    live = args.live and pipeline_enabled()
    if args.live and not live:
        print("PIPELINE_ENABLED is not true: doing a dry run instead")
    yt = YouTube(Credentials.from_env(), Governor(state, settings)) if live else None
    for o in publish_day(state, settings, day, live=live, yt=yt):
        print(f"{o.slot.isoformat()}  {o.status:9} {o.job_id or '-':24} {o.video_id or ''} "
              f"{o.detail}")
    state.close()
    return 0


def cmd_nightly(args: argparse.Namespace) -> int:
    import logging

    from pipeline.nightly import run_night

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    rep = run_night(offline=args.offline, live=not args.dry_run, max_jobs=args.max_jobs)
    print(f"produced: {rep.produced}\nfailed: {rep.failed}\nstopped_by: {rep.stopped_by}")
    for o in rep.published:
        print(f"{o.slot.isoformat()}  {o.status:9} {o.job_id or '-'} {o.video_id or ''}")
    return 0


def cmd_healthcheck(args: argparse.Namespace) -> int:
    from pipeline.nightly import healthcheck

    for o in healthcheck(live=not args.dry_run):
        print(f"{o.slot.isoformat()}  {o.status:9} {o.job_id or '-'} {o.video_id or ''}")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    from pipeline import alerts, digest

    body = digest.build(State(), load_settings())
    if args.post:
        from datetime import date

        alerts.notify(f"Weekly digest: {date.today().isoformat()}", body, label="digest")
    else:
        print(body)
    return 0


def cmd_weekly(args: argparse.Namespace) -> int:
    import logging
    from datetime import UTC, datetime

    from pipeline import alerts, digest
    from pipeline.budget import Governor
    from pipeline.jobs import Job
    from pipeline.llm import LLM, Completer
    from pipeline.offline import OfflineLLM
    from pipeline.stages import compilation
    from pipeline.youtube import Credentials, YouTube

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    settings, state = load_settings(), State()
    gov = Governor(state, settings)
    llm: Completer = OfflineLLM(gov) if args.offline else LLM(gov)
    now = datetime.now(UTC)
    week_job = Job(f"weekly-{now.date().isoformat()}")
    try:
        video, meta = compilation.build(llm, state, settings, week_job, now=now,
                                        offline=args.offline,
                                        reuse=True if args.offline else None)
    except RuntimeError as e:
        print(f"no compilation this week: {e}")
        alerts.notify("Weekly compilation skipped", str(e))
        return 0
    report = compilation.qa_compilation(llm, video, week_job)
    for c in report.checks:
        print(f"{'PASS' if c.passed else 'FAIL'}  {c.name:14} {c.detail}")
    if not report.passed:
        alerts.notify("Weekly compilation failed QA",
                      "\n".join(f"- {c.name}: {c.detail}" for c in report.checks if not c.passed))
        return 2
    live = not args.dry_run and pipeline_enabled()
    yt = YouTube(Credentials.from_env(), gov) if live else None
    slot = compilation.publish_slot(now.astimezone().date(), settings)
    res = compilation.publish(video, meta, week_job, settings, slot, live=live, yt=yt)
    print(json.dumps({k: v for k, v in res.items() if k != "snippet"}, indent=2, default=str))
    if args.post_digest:
        alerts.notify(f"Weekly digest: {now.date().isoformat()}", digest.build(state, settings),
                      label="digest")
    return 0


def cmd_analytics(args: argparse.Namespace) -> int:
    from pipeline import analytics
    from pipeline.budget import Governor
    from pipeline.stages import publish
    from pipeline.youtube import Credentials, YouTube

    settings, state = load_settings(), State()
    publish.init(state)
    try:
        yt = YouTube(Credentials.from_env(), Governor(state, settings))
    except RuntimeError as e:
        print(f"skipped: {e}")
        return 0
    print(f"updated stats for {analytics.fetch(yt, state)} videos")
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    from pipeline import analytics
    from pipeline.budget import Governor
    from pipeline.llm import LLM, Completer
    from pipeline.offline import OfflineLLM
    from pipeline.stages import publish

    settings, state = load_settings(), State()
    publish.init(state)
    gov = Governor(state, settings)
    llm: Completer = OfflineLLM(gov) if args.offline else LLM(gov)
    plan = analytics.plan_week(llm, state, settings)
    print("not enough data yet (need 6 videos with stats)" if plan is None else
          json.dumps(analytics.summary(state), indent=2))
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
    m = sub.add_parser("make-short", help="produce one short end to end (no upload)")
    m.add_argument("--job-id", required=True)
    m.add_argument("--case", default="", help="optional hint: a specific case or theme")
    m.add_argument("--offline", action="store_true",
                   help="fictional fixture case, silent voice, procedural art; no network")
    m.add_argument("--urgent", action="store_true",
                   help="allow Claude calls outside the overnight window")
    m.set_defaults(fn=cmd_make_short)
    pub = sub.add_parser("publish", help="schedule buffered shorts into today's slots")
    pub.add_argument("--date", default="", help="YYYY-MM-DD (default: today)")
    pub.add_argument("--live", action="store_true",
                     help="really upload (also requires PIPELINE_ENABLED=true)")
    pub.set_defaults(fn=cmd_publish)
    n = sub.add_parser("nightly", help="produce tonight's shorts, refill buffer, schedule")
    n.add_argument("--offline", action="store_true")
    n.add_argument("--dry-run", action="store_true", help="never upload")
    n.add_argument("--max-jobs", type=int, default=None)
    n.set_defaults(fn=cmd_nightly)
    h = sub.add_parser("healthcheck", help="fill open slots in the next 12 h from the buffer")
    h.add_argument("--dry-run", action="store_true")
    h.set_defaults(fn=cmd_healthcheck)
    w = sub.add_parser("weekly", help="build, check and schedule the Sunday compilation")
    w.add_argument("--offline", action="store_true")
    w.add_argument("--dry-run", action="store_true")
    w.add_argument("--post-digest", action="store_true")
    w.set_defaults(fn=cmd_weekly)
    sub.add_parser("analytics", help="pull YouTube Analytics for recent videos").set_defaults(
        fn=cmd_analytics)
    ln = sub.add_parser("learn", help="weekly planner: insights, case mix, writer notes")
    ln.add_argument("--offline", action="store_true")
    ln.set_defaults(fn=cmd_learn)
    dg = sub.add_parser("digest", help="weekly owner digest")
    dg.add_argument("--post", action="store_true", help="open it as a GitHub issue")
    dg.set_defaults(fn=cmd_digest)
    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
