"""Stage 8b: cross-post published shorts to TikTok and Instagram Reels (Phase 8).

Neither API schedules posts the way YouTube's publishAt does, so this runs shortly after
each slot and posts whatever has gone public on YouTube but isn't on the other platform yet.
A failure on one platform never blocks the other or YouTube. Same stdlib HTTP approach as
the YouTube client, with an injectable transport for tests.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from pipeline.config import CONFIG_DIR, pipeline_enabled
from pipeline.jobs import JOBS_DIR, Job
from pipeline.schemas import Script
from pipeline.state import State, now_iso
from pipeline.youtube import HttpResponse, Transport, urllib_transport

SCHEMA = """
CREATE TABLE IF NOT EXISTS crossposts (
    job_id     TEXT NOT NULL,
    platform   TEXT NOT NULL,          -- tiktok | instagram
    status     TEXT NOT NULL,          -- posted | failed | dry_run
    post_id    TEXT,
    error      TEXT,
    attempts   INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, platform)
);
"""
MAX_ATTEMPTS = 3
DISCLOSURE = "AI-assisted visuals and narration. Real case, researched from public sources."


class CrosspostError(RuntimeError):
    pass


def load_config() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((CONFIG_DIR / "crosspost.yaml").read_text())
    return data


def caption(sc: Script, limit: int) -> str:
    tags = " ".join(h if h.startswith("#") else f"#{h}" for h in
                    [*sc.hashtags[:3], "#coldcase", "#unsolved", "#truecrime"])
    text = f"{sc.titles[0]}\n\n{sc.hook}\n\n{tags}\n{DISCLOSURE}"
    return text[:limit]


def _check(r: HttpResponse, what: str) -> Any:
    if r.status >= 400:
        raise CrosspostError(f"{what}: HTTP {r.status}: {r.body[:300]!r}")
    return r.json()


# ---------------- TikTok ----------------
@dataclass
class TikTok:
    client_key: str
    client_secret: str
    refresh_token: str
    privacy_level: str = "SELF_ONLY"
    http: Transport = urllib_transport
    poll_s: float = 5.0
    rotated: bool = False
    API = "https://open.tiktokapis.com/v2"

    @classmethod
    def from_env(cls, privacy_level: str) -> TikTok:
        keys = ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")
        missing = [k for k in keys if not os.environ.get(k)]
        if missing:
            raise CrosspostError(f"missing TikTok secrets: {', '.join(missing)}")
        return cls(os.environ[keys[0]], os.environ[keys[1]], os.environ[keys[2]],
                   privacy_level=privacy_level)

    def token(self) -> str:
        body = urllib.parse.urlencode({
            "client_key": self.client_key, "client_secret": self.client_secret,
            "grant_type": "refresh_token", "refresh_token": self.refresh_token}).encode()
        data = _check(self.http("POST", f"{self.API}/oauth/token/",
                                {"Content-Type": "application/x-www-form-urlencoded"}, body),
                      "tiktok token")
        if data.get("refresh_token") and data["refresh_token"] != self.refresh_token:
            # TikTok may rotate refresh tokens. We can't write GitHub secrets from a workflow,
            # so flag it for the owner (never log the token itself).
            self.rotated = True
        return str(data["access_token"])

    def post(self, video: Path, text: str) -> str:
        tok = self.token()
        size = video.stat().st_size
        chunk = min(size, 10 * 1024 * 1024)
        count = max(1, math.floor(size / chunk))
        init = _check(self.http("POST", f"{self.API}/post/publish/video/init/", {
            "Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"},
            json.dumps({
                "post_info": {"title": text, "privacy_level": self.privacy_level,
                              "disable_duet": False, "disable_comment": False,
                              "disable_stitch": False, "is_aigc": True},
                "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                "chunk_size": chunk, "total_chunk_count": count},
            }).encode()), "tiktok init")["data"]
        url, pid = str(init["upload_url"]), str(init["publish_id"])
        with video.open("rb") as f:
            for i in range(count):
                start = i * chunk
                data = f.read(size - start if i == count - 1 else chunk)
                end = start + len(data) - 1
                r = self.http("PUT", url, {"Content-Type": "video/mp4",
                                           "Content-Range": f"bytes {start}-{end}/{size}",
                                           "Content-Length": str(len(data))}, data)
                if r.status not in (200, 201, 206):
                    raise CrosspostError(f"tiktok upload chunk {i}: HTTP {r.status}")
        for _ in range(60):
            st = _check(self.http("POST", f"{self.API}/post/publish/status/fetch/", {
                "Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                json.dumps({"publish_id": pid}).encode()), "tiktok status")["data"]
            if st.get("status") == "PUBLISH_COMPLETE":
                ids = st.get("publicaly_available_post_id") or st.get("publicly_available_post_id")
                return str(ids[0]) if ids else pid
            if st.get("status") == "FAILED":
                raise CrosspostError(f"tiktok publish failed: {st.get('fail_reason')}")
            time.sleep(self.poll_s)
        return pid   # still processing; TikTok will finish it


# ---------------- Instagram ----------------
@dataclass
class Instagram:
    user_id: str
    access_token: str
    version: str = "v21.0"
    http: Transport = urllib_transport
    poll_s: float = 10.0

    @classmethod
    def from_env(cls, version: str) -> Instagram:
        if not os.environ.get("META_IG_USER_ID") or not os.environ.get("META_ACCESS_TOKEN"):
            raise CrosspostError("missing META_IG_USER_ID / META_ACCESS_TOKEN")
        return cls(os.environ["META_IG_USER_ID"], os.environ["META_ACCESS_TOKEN"], version)

    @property
    def graph(self) -> str:
        return f"https://graph.facebook.com/{self.version}"

    def post(self, video: Path, text: str) -> str:
        q = urllib.parse.urlencode({"media_type": "REELS", "upload_type": "resumable",
                                    "caption": text, "share_to_feed": "true",
                                    "access_token": self.access_token})
        cid = str(_check(self.http("POST", f"{self.graph}/{self.user_id}/media?{q}", {}, None),
                         "ig container")["id"])
        size = video.stat().st_size
        _check(self.http("POST", f"https://rupload.facebook.com/ig-api-upload/{self.version}/{cid}",
                         {"Authorization": f"OAuth {self.access_token}", "offset": "0",
                          "file_size": str(size)}, video.read_bytes()), "ig upload")
        for _ in range(60):
            st = _check(self.http("GET", f"{self.graph}/{cid}?fields=status_code,status"
                                  f"&access_token={self.access_token}", {}, None), "ig status")
            if st.get("status_code") == "FINISHED":
                break
            if st.get("status_code") in ("ERROR", "EXPIRED"):
                raise CrosspostError(f"ig processing: {st.get('status')}")
            time.sleep(self.poll_s)
        else:
            raise CrosspostError("ig processing timed out")
        pub = _check(self.http("POST", f"{self.graph}/{self.user_id}/media_publish?"
                               + urllib.parse.urlencode({"creation_id": cid,
                                                         "access_token": self.access_token}),
                               {}, None), "ig publish")
        return str(pub["id"])


# ---------------- orchestration ----------------
def init(state: State) -> None:
    state.conn.executescript(SCHEMA)


def due(state: State, platform: str, now: datetime, window_h: float) -> list[str]:
    """Jobs public on YouTube within the window and not yet (successfully) cross-posted."""
    from pipeline.stages import publish

    publish.init(state)
    init(state)
    rows = state.conn.execute(
        "SELECT p.job_id, p.slot FROM publications p WHERE p.platform='youtube' "
        "AND p.status='scheduled' AND NOT EXISTS (SELECT 1 FROM crossposts c WHERE "
        "c.job_id = p.job_id AND c.platform = ? AND (c.status IN ('posted', 'dry_run') "
        "OR c.attempts >= ?))", (platform, MAX_ATTEMPTS)).fetchall()
    out = []
    for job_id, slot in rows:
        t = datetime.fromisoformat(slot)
        if now - timedelta(hours=window_h) <= t <= now:
            out.append(job_id)
    return out


def _record(state: State, job_id: str, platform: str, status: str, post_id: str | None,
            error: str | None) -> None:
    with state.tx() as c:
        c.execute(
            "INSERT INTO crossposts (job_id, platform, status, post_id, error, updated_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(job_id, platform) DO UPDATE SET "
            "status=excluded.status, post_id=excluded.post_id, error=excluded.error, "
            "attempts=crossposts.attempts + 1, updated_at=excluded.updated_at",
            (job_id, platform, status, post_id, error, now_iso()))


def run(state: State, *, live: bool, now: datetime | None = None,
        clients: dict[str, Any] | None = None, jobs_dir: Path = JOBS_DIR) -> list[dict[str, str]]:
    now = now or datetime.now(UTC)
    cfg = load_config()
    really = live and pipeline_enabled()
    results: list[dict[str, str]] = []
    limits = {"tiktok": 2200, "instagram": 2200}
    for platform in ("tiktok", "instagram"):
        if not cfg.get(platform, {}).get("enabled"):
            continue
        jobs = due(state, platform, now, float(cfg.get("window_hours", 36)))
        if not jobs:
            continue
        client = (clients or {}).get(platform)
        if really and client is None:
            try:
                client = (TikTok.from_env(cfg["tiktok"].get("privacy_level", "SELF_ONLY"))
                          if platform == "tiktok"
                          else Instagram.from_env(cfg["instagram"].get("graph_version", "v21.0")))
            except CrosspostError as e:
                results.append({"platform": platform, "status": "skipped", "detail": str(e)})
                continue
        for job_id in jobs:
            job = Job(job_id, jobs_dir)
            video = job.path("short.mp4")
            if not video.exists():
                _record(state, job_id, platform, "failed", None, "video file missing")
                results.append({"platform": platform, "job": job_id, "status": "failed",
                                "detail": "video file missing"})
                continue
            text = caption(job.load("script.json", Script), limits[platform])
            if not really:
                _record(state, job_id, platform, "dry_run", None, None)
                results.append({"platform": platform, "job": job_id, "status": "dry_run"})
                continue
            try:
                pid = client.post(video, text)  # type: ignore[union-attr]
                _record(state, job_id, platform, "posted", pid, None)
                results.append({"platform": platform, "job": job_id, "status": "posted",
                                "detail": pid})
            except Exception as e:  # noqa: BLE001 - one platform/job failing never blocks others
                _record(state, job_id, platform, "failed", None, str(e)[:500])
                results.append({"platform": platform, "job": job_id, "status": "failed",
                                "detail": str(e)[:200]})
        if getattr(client, "rotated", False):
            from pipeline import alerts

            alerts.notify("TikTok refresh token rotated",
                          "TikTok issued a new refresh token. Re-run the TikTok auth step and "
                          "update the TIKTOK_REFRESH_TOKEN secret (SETUP step 12).")
    return results
