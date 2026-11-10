import copy
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from pipeline import offline
from pipeline.budget import Governor, QuotaExceeded
from pipeline.jobs import Job
from pipeline.schemas import CaseCandidate, FactPack, Script
from pipeline.stages import publish
from pipeline.state import JobStatus, Stage
from pipeline.youtube import Credentials, HttpResponse, YouTube, YouTubeError

DAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)          # 01:00 ET, before all slots


class FakeYT:
    """Records requests; emulates token, resumable upload and simple JSON endpoints."""

    def __init__(self, fail_upload=False):
        self.reqs = []
        self.fail_upload = fail_upload
        self.n = 0

    def __call__(self, method, url, headers, body):
        self.reqs.append((method, url, headers, body))
        if "oauth2" in url:
            return HttpResponse(200, {}, b'{"access_token": "tok"}')
        if "uploadType=resumable" in url:
            if self.fail_upload:
                return HttpResponse(403, {}, b'{"error": "forbidden"}')
            return HttpResponse(200, {"location": "https://upload.example/session"}, b"")
        if url.startswith("https://upload.example/session"):
            self.n += 1
            return HttpResponse(200, {}, json.dumps({"id": f"vid{self.n}"}).encode())
        return HttpResponse(200, {}, b'{"id": "x", "items": []}')


def make_job(tmp_path, state, job_id, added_at):
    job = Job(job_id, tmp_path)
    job.save("case.json", CaseCandidate.model_validate(offline.CASE))
    job.save("fact_pack.json", FactPack.model_validate(copy.deepcopy(offline.FACT_PACK)))
    job.save("script.json", Script.model_validate(copy.deepcopy(offline.SCRIPT)))
    job.path("short.mp4").write_bytes(b"\x00" * 1000)
    state.upsert_job(job_id, "short", Stage.QA, JobStatus.DONE, meta={"case_no": "CASE #0007"})
    state.add_to_buffer(job_id)
    state.conn.execute("UPDATE buffer SET added_at = ? WHERE job_id = ?", (added_at, job_id))
    state.conn.commit()
    return job


@pytest.fixture(autouse=True)
def isolate_files(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "PUBLISHED", tmp_path / "published.json")
    monkeypatch.setattr(publish, "IDS_FILE", tmp_path / "ids.json")
    (tmp_path / "ids.json").write_text(json.dumps(
        {"channel_id": "UC1", "playlists": {"Still Missing": "PL1", "By Decade: 1980s": "PL2"}}))


def yt_client(state, settings, transport):
    return YouTube(Credentials("id", "secret", "refresh"), Governor(state, settings, now=NOW),
                   transport)


def test_slots_are_eastern(settings):
    slots = publish.slots_for(DAY, settings)
    assert [s.strftime("%H:%M") for s in slots] == ["08:00", "14:00", "20:00"]
    assert slots[0].astimezone(UTC).hour == 13              # 08:00 EST


def test_open_slots_skip_past_and_taken(state, settings):
    late = datetime(2026, 11, 12, 18, 50, tzinfo=UTC)       # 13:50 ET: 14:00 too close
    assert [s.strftime("%H:%M") for s in publish.open_slots(state, DAY, settings, late)] == [
        "20:00"]


def test_choose_job_prefers_fresh_then_oldest(tmp_path, state):
    make_job(tmp_path, state, "old", (NOW - timedelta(days=3)).isoformat())
    make_job(tmp_path, state, "fresh", (NOW - timedelta(hours=2)).isoformat())
    assert publish.choose_job(state, tmp_path, NOW) == "fresh"
    state.take_from_buffer("s", job_id="fresh")
    assert publish.choose_job(state, tmp_path, NOW) == "old"


def test_plan_metadata(tmp_path, state, settings):
    job = make_job(tmp_path, state, "j1", NOW.isoformat())
    plan = publish.build_plan(job, publish.slots_for(DAY, settings)[0], settings, "CASE #0007")
    st = plan.status()
    assert st["privacyStatus"] == "private" and st["publishAt"] == "2026-11-12T13:00:00Z"
    assert st["containsSyntheticMedia"] is True and st["selfDeclaredMadeForKids"] is False
    assert "Case #0007" in plan.description and "example.org" in plan.description
    assert "AI-assisted" in plan.description
    assert plan.playlists == ["Still Missing", "By Decade: 1980s"]
    assert sum(len(t) + 1 for t in plan.tags) <= 500


def test_dry_run_by_default(tmp_path, state, settings, monkeypatch):
    monkeypatch.setenv("PIPELINE_ENABLED", "true")
    make_job(tmp_path, state, "j1", NOW.isoformat())
    out = publish.publish_day(state, settings, DAY, live=False, now=NOW, jobs_dir=tmp_path)
    assert out[0].status == "dry_run" and out[1].status == "empty"
    assert (tmp_path / "j1" / "publish_plan.json").exists()


def test_kill_switch_blocks_live(tmp_path, state, settings, monkeypatch):
    monkeypatch.setenv("PIPELINE_ENABLED", "false")
    make_job(tmp_path, state, "j1", NOW.isoformat())
    fake = FakeYT()
    out = publish.publish_day(state, settings, DAY, live=True, now=NOW, jobs_dir=tmp_path,
                              yt=yt_client(state, settings, fake))
    assert out[0].status == "dry_run" and fake.reqs == []


def test_live_publish_uploads_playlists_comment(tmp_path, state, settings, monkeypatch):
    monkeypatch.setenv("PIPELINE_ENABLED", "true")
    make_job(tmp_path, state, "j1", NOW.isoformat())
    fake = FakeYT()
    yt = yt_client(state, settings, fake)
    out = publish.publish_day(state, settings, DAY, live=True, now=NOW, jobs_dir=tmp_path, yt=yt)
    assert out[0].status == "scheduled" and out[0].video_id == "vid1"
    urls = [u for _, u, _, _ in fake.reqs]
    assert sum("playlistItems" in u for u in urls) == 2
    assert any("commentThreads" in u for u in urls)
    meta = json.loads(next(b for _, u, _, b in fake.reqs if "resumable" in u))
    assert meta["status"]["publishAt"] == "2026-11-12T13:00:00Z"
    assert json.loads(publish.PUBLISHED.read_text())[0]["video_id"] == "vid1"
    used = 1600 + 50 * 3
    assert yt.gov.youtube_quota_left() == settings.budget.youtube_quota.daily_units - used
    # slot is now taken; a second run schedules nothing new for it
    again = publish.publish_day(state, settings, DAY, live=True, now=NOW, jobs_dir=tmp_path,
                                yt=yt)
    assert all(o.slot != out[0].slot for o in again)


def test_failed_upload_recorded_and_others_continue(tmp_path, state, settings, monkeypatch):
    monkeypatch.setenv("PIPELINE_ENABLED", "true")
    make_job(tmp_path, state, "j1", NOW.isoformat())
    make_job(tmp_path, state, "j2", NOW.isoformat())
    out = publish.publish_day(state, settings, DAY, live=True, now=NOW, jobs_dir=tmp_path,
                              yt=yt_client(state, settings, FakeYT(fail_upload=True)))
    assert [o.status for o in out[:2]] == ["failed", "failed"]
    assert len(state.buffer_available()) == 2               # failed videos stay buffered


def test_resumable_upload_handles_308(tmp_path, state, settings):
    calls = {"n": 0}

    def transport(method, url, headers, body):
        if "oauth2" in url:
            return HttpResponse(200, {}, b'{"access_token": "t"}')
        if "resumable" in url:
            return HttpResponse(200, {"location": "https://u/s"}, b"")
        calls["n"] += 1
        if calls["n"] == 1:
            return HttpResponse(308, {"range": "bytes=0-499"}, b"")
        assert headers["Content-Range"].startswith("bytes 500-")
        return HttpResponse(201, {}, b'{"id": "v9"}')

    f = tmp_path / "v.mp4"
    f.write_bytes(b"\x01" * 1000)
    yt = yt_client(state, settings, transport)
    assert yt.upload_video(f, {}, {}) == "v9"


def test_quota_refuses_before_request(state, settings):
    fake = FakeYT()
    yt = yt_client(state, settings, fake)
    yt.gov.use_youtube_quota("prior", settings.budget.youtube_quota.daily_units - 10)
    with pytest.raises(QuotaExceeded):
        yt.add_to_playlist("PL", "v")
    assert not any("playlistItems" in u for _, u, _, _ in fake.reqs)


def test_token_failure_is_clear(state, settings):
    yt = yt_client(state, settings, lambda m, u, h, b: HttpResponse(400, {}, b"bad"))
    with pytest.raises(YouTubeError, match="auth_youtube"):
        yt.token()


def test_credentials_from_env_reports_missing(monkeypatch):
    for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="YOUTUBE_CLIENT_ID"):
        Credentials.from_env()
