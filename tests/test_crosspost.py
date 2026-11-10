import copy
import json
from datetime import UTC, datetime, timedelta

import pytest

from pipeline import crosspost, offline
from pipeline.jobs import Job
from pipeline.schemas import Script
from pipeline.stages import publish
from pipeline.youtube import HttpResponse

NOW = datetime(2026, 11, 12, 13, 10, tzinfo=UTC)


@pytest.fixture
def enabled(monkeypatch):
    cfg = {"tiktok": {"enabled": True, "privacy_level": "SELF_ONLY"},
           "instagram": {"enabled": True, "graph_version": "v21.0"}, "window_hours": 36}
    monkeypatch.setattr(crosspost, "load_config", lambda: cfg)
    monkeypatch.setenv("PIPELINE_ENABLED", "true")
    return cfg


def seed(state, tmp_path, job_id, slot):
    publish.init(state)
    j = Job(job_id, tmp_path)
    j.save("script.json", Script.model_validate(copy.deepcopy(offline.SCRIPT)))
    j.path("short.mp4").write_bytes(b"\x00" * 3000)
    state.conn.execute("INSERT INTO publications VALUES (?,?,?,?,?,?,?,?)",
                       (job_id, "youtube", slot.isoformat(), "scheduled", "vid", "t", None,
                        slot.isoformat()))
    state.conn.commit()


class Ok:
    def __init__(self):
        self.posts = []

    def post(self, video, text):
        self.posts.append(text)
        return f"p{len(self.posts)}"


class Boom:
    def post(self, video, text):
        raise RuntimeError("platform down")


def test_due_only_after_slot_within_window(state, tmp_path):
    seed(state, tmp_path, "past", NOW - timedelta(minutes=10))
    seed(state, tmp_path, "future", NOW + timedelta(hours=5))
    seed(state, tmp_path, "old", NOW - timedelta(days=3))
    assert crosspost.due(state, "tiktok", NOW, 36) == ["past"]


def test_posts_each_platform_once_with_disclosure(state, tmp_path, enabled):
    seed(state, tmp_path, "j1", NOW - timedelta(minutes=10))
    tt, ig = Ok(), Ok()
    res = crosspost.run(state, live=True, now=NOW, clients={"tiktok": tt, "instagram": ig},
                        jobs_dir=tmp_path)
    assert {r["status"] for r in res} == {"posted"}
    assert crosspost.DISCLOSURE in tt.posts[0]
    again = crosspost.run(state, live=True, now=NOW, clients={"tiktok": tt, "instagram": ig},
                          jobs_dir=tmp_path)
    assert again == [] and len(tt.posts) == 1


def test_one_platform_failing_doesnt_block_other(state, tmp_path, enabled):
    seed(state, tmp_path, "j1", NOW - timedelta(minutes=10))
    ig = Ok()
    res = crosspost.run(state, live=True, now=NOW, clients={"tiktok": Boom(), "instagram": ig},
                        jobs_dir=tmp_path)
    by = {r["platform"]: r["status"] for r in res}
    assert by == {"tiktok": "failed", "instagram": "posted"}


def test_failed_retries_then_gives_up(state, tmp_path, enabled):
    seed(state, tmp_path, "j1", NOW - timedelta(minutes=10))
    for _ in range(crosspost.MAX_ATTEMPTS):
        crosspost.run(state, live=True, now=NOW, clients={"tiktok": Boom(), "instagram": Ok()},
                      jobs_dir=tmp_path)
    assert crosspost.due(state, "tiktok", NOW, 36) == []


def test_dry_run_when_disabled(state, tmp_path, enabled, monkeypatch):
    monkeypatch.setenv("PIPELINE_ENABLED", "false")
    seed(state, tmp_path, "j1", NOW - timedelta(minutes=10))
    tt = Ok()
    res = crosspost.run(state, live=True, now=NOW, clients={"tiktok": tt, "instagram": Ok()},
                        jobs_dir=tmp_path)
    assert {r["status"] for r in res} == {"dry_run"} and tt.posts == []


def test_disabled_platforms_skipped(state, tmp_path, monkeypatch):
    monkeypatch.setattr(crosspost, "load_config", lambda: {"tiktok": {"enabled": False},
                                                           "instagram": {"enabled": False}})
    seed(state, tmp_path, "j1", NOW - timedelta(minutes=10))
    assert crosspost.run(state, live=True, now=NOW, jobs_dir=tmp_path) == []


def test_tiktok_flow_and_aigc_flag(tmp_path):
    reqs = []

    def http(method, url, headers, body):
        reqs.append((method, url, body))
        if "oauth/token" in url:
            return HttpResponse(200, {}, b'{"access_token": "a", "refresh_token": "r"}')
        if "video/init" in url:
            return HttpResponse(200, {}, json.dumps({"data": {
                "upload_url": "https://up/x", "publish_id": "pub1"}}).encode())
        if url.startswith("https://up/"):
            return HttpResponse(201, {}, b"")
        return HttpResponse(200, {}, json.dumps({"data": {
            "status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [123]}}).encode())

    v = tmp_path / "v.mp4"
    v.write_bytes(b"\x01" * 2000)
    tt = crosspost.TikTok("k", "s", "r", http=http, poll_s=0)
    assert tt.post(v, "caption") == "123"
    init = json.loads(next(b for m, u, b in reqs if "video/init" in u))
    assert init["post_info"]["is_aigc"] is True
    assert init["post_info"]["privacy_level"] == "SELF_ONLY"
    assert init["source_info"]["video_size"] == 2000


def test_instagram_flow(tmp_path):
    def http(method, url, headers, body):
        if url.endswith("fields=status_code,status&access_token=t") or "status_code" in url:
            return HttpResponse(200, {}, b'{"status_code": "FINISHED"}')
        if "rupload" in url:
            assert headers["file_size"] == "1500"
            return HttpResponse(200, {}, b'{"success": true}')
        if "media_publish" in url:
            return HttpResponse(200, {}, b'{"id": "ig9"}')
        return HttpResponse(200, {}, b'{"id": "c1"}')

    v = tmp_path / "v.mp4"
    v.write_bytes(b"\x01" * 1500)
    assert crosspost.Instagram("u", "t", http=http, poll_s=0).post(v, "cap") == "ig9"


def test_caption_limits():
    sc = Script.model_validate(copy.deepcopy(offline.SCRIPT))
    assert len(crosspost.caption(sc, 50)) == 50
