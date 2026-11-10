from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from pipeline import alerts, nightly
from pipeline.budget import SubscriptionLimited
from pipeline.run import Result
from pipeline.schemas import Check, QAReport
from pipeline.stages import publish

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github").rglob("*.yml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_yaml_parses(path):
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict)


def test_scheduled_workflows_share_state_lock():
    for name in ("nightly.yml", "healthcheck.yml", "weekly.yml"):
        wf = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
        assert wf["concurrency"]["group"] == "pipeline-state"
        assert "PIPELINE_ENABLED" in next(iter(wf["jobs"].values()))["if"]


def test_no_api_key_in_workflows():
    for p in WORKFLOWS:
        assert "ANTHROPIC_API_KEY" not in p.read_text(), p


class FakeIssues:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.calls = []

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        if method == "GET":
            return self.existing
        return {}


def test_alerts_suppressed_while_disabled(monkeypatch, capsys):
    monkeypatch.setenv("PIPELINE_ENABLED", "false")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert alerts.notify("Buffer low", "x") == "printed"
    assert "suppressed" in capsys.readouterr().out


def test_alert_creates_then_comments(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    gh = FakeIssues()
    assert alerts.notify("Buffer low", "x", github=gh) == "created"
    gh2 = FakeIssues([{"title": "Buffer low", "number": 7}])
    assert alerts.notify("Buffer low", "y", github=gh2) == "commented"
    assert gh2.calls[-1][1].endswith("/issues/7/comments")


def test_alert_prints_without_github(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert alerts.notify("t", "b") == "printed"
    assert "t" in capsys.readouterr().out


def _passed(job_id):
    return Result(job=None, video="v",
                  report=QAReport(job_id=job_id, checks=[Check(name="x", passed=True)],
                                  quality_score=8))


def test_target_count_refills_buffer(state, settings):
    assert nightly.target_count(state, settings) == (
        settings.schedule.shorts_per_day + settings.schedule.buffer.target)


def test_night_stops_on_subscription_limit(state, settings, monkeypatch):
    calls = []

    def fake_make(job_id, **kw):
        calls.append(job_id)
        if len(calls) == 3:
            raise SubscriptionLimited("limit")
        return _passed(job_id)

    monkeypatch.setattr(nightly, "make_short", fake_make)
    monkeypatch.setattr(nightly.publish, "publish_day", lambda *a, **k: [])
    monkeypatch.setattr(nightly.alerts, "notify", lambda *a, **k: "printed")
    rep = nightly.run_night(state, settings, live=False, today=date(2026, 11, 12))
    assert rep.produced == ["2026-11-12-01", "2026-11-12-02"]
    assert rep.stopped_by == "limit"


def test_night_survives_crashing_job(state, settings, monkeypatch):
    def fake_make(job_id, **kw):
        if job_id.endswith("01"):
            raise ValueError("boom")
        return _passed(job_id)

    monkeypatch.setattr(nightly, "make_short", fake_make)
    monkeypatch.setattr(nightly.publish, "publish_day", lambda *a, **k: [])
    monkeypatch.setattr(nightly.alerts, "notify", lambda *a, **k: "printed")
    rep = nightly.run_night(state, settings, live=False, max_jobs=2, today=date(2026, 11, 12))
    assert len(rep.produced) == 2 and "boom" in rep.failed[0]


def test_empty_slot_raises_alert(state, settings, monkeypatch):
    sent = []
    monkeypatch.setattr(nightly.alerts, "notify", lambda t, b, **k: sent.append(t))
    slot = datetime(2026, 11, 12, 13, 0, tzinfo=UTC)
    monkeypatch.setattr(nightly.publish, "publish_day",
                        lambda *a, **k: [publish.Outcome(slot, None, "empty", detail="none")])
    nightly.run_night(state, settings, live=False, max_jobs=0, today=date(2026, 11, 12))
    assert any("not filled" in t for t in sent) and any("Buffer low" in t for t in sent)


def test_healthcheck_only_touches_next_12h(state, settings, monkeypatch):
    seen = []

    def fake_publish(state_, settings_, day, **kw):
        seen.append(day)
        return [publish.Outcome(s, None, "empty") for s in publish.slots_for(day, settings_)]

    monkeypatch.setattr(nightly.publish, "publish_day", fake_publish)
    monkeypatch.setattr(nightly.alerts, "notify", lambda *a, **k: "printed")
    now = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)          # 10:00 ET
    out = nightly.healthcheck(state, settings, now=now, live=False)
    assert all(o.slot - now <= timedelta(hours=12) for o in out)
    # 08:00 ET is past; 14:00 and 20:00 ET (19:00, 01:00 UTC) are within 12 h
    assert {o.slot.astimezone(UTC).hour for o in out} == {19, 1}
