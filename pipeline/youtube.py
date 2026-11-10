"""Minimal YouTube Data API v3 client over stdlib HTTP (no Google SDK dependency).

Every call is charged to the governor's daily quota *before* it is made. The HTTP
transport is injectable so tests never touch the network.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.budget import Governor

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
CHUNK = 8 * 1024 * 1024


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body or b"{}")


Transport = Callable[[str, str, dict[str, str], bytes | None], HttpResponse]


def urllib_transport(method: str, url: str, headers: dict[str, str],
                     body: bytes | None) -> HttpResponse:  # pragma: no cover - network
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return HttpResponse(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
    except urllib.error.HTTPError as e:
        return HttpResponse(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read())


class YouTubeError(RuntimeError):
    def __init__(self, status: int, body: bytes, what: str) -> None:
        super().__init__(f"{what}: HTTP {status}: {body[:500]!r}")
        self.status = status


@dataclass(frozen=True)
class Credentials:
    client_id: str
    client_secret: str
    refresh_token: str

    @classmethod
    def from_env(cls) -> Credentials:
        missing = [k for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
                               "YOUTUBE_REFRESH_TOKEN") if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"missing YouTube secrets: {', '.join(missing)} (SETUP step 4)")
        return cls(os.environ["YOUTUBE_CLIENT_ID"], os.environ["YOUTUBE_CLIENT_SECRET"],
                   os.environ["YOUTUBE_REFRESH_TOKEN"])


# Quota cost per method (units), per YouTube Data API docs.
COST = {"videos.insert": 1600, "thumbnails.set": 50, "playlistItems.insert": 50,
        "commentThreads.insert": 50, "channels.update": 50, "playlists.insert": 50,
        "playlists.list": 1, "channels.list": 1, "videos.list": 1, "watermarks.set": 50,
        "channelBanners.insert": 50, "videos.update": 50}


class YouTube:
    def __init__(self, creds: Credentials, gov: Governor,
                 transport: Transport = urllib_transport) -> None:
        self.creds, self.gov, self.http = creds, gov, transport
        self._token: str | None = None

    # ----- auth -----
    def token(self) -> str:
        if self._token is None:
            body = urllib.parse.urlencode({
                "client_id": self.creds.client_id, "client_secret": self.creds.client_secret,
                "refresh_token": self.creds.refresh_token, "grant_type": "refresh_token",
            }).encode()
            r = self.http("POST", TOKEN_URL,
                          {"Content-Type": "application/x-www-form-urlencoded"}, body)
            if r.status != 200:
                raise YouTubeError(r.status, r.body, "token refresh (re-run auth_youtube.py)")
            self._token = str(r.json()["access_token"])
        return self._token

    def _call(self, op: str, method: str, url: str, body: Any = None,
              headers: dict[str, str] | None = None, raw: bytes | None = None) -> HttpResponse:
        self.gov.use_youtube_quota(op, COST[op])
        h = {"Authorization": f"Bearer {self.token()}", **(headers or {})}
        data = raw
        if body is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        r = self.http(method, url, h, data)
        if r.status >= 400:
            raise YouTubeError(r.status, r.body, op)
        return r

    # ----- videos -----
    def upload_video(self, path: Path, snippet: dict[str, Any], status: dict[str, Any]) -> str:
        """Resumable upload. Returns the new video id."""
        size = path.stat().st_size
        r = self._call("videos.insert", "POST",
                       f"{UPLOAD}/videos?uploadType=resumable&part=snippet,status",
                       body={"snippet": snippet, "status": status},
                       headers={"X-Upload-Content-Type": "video/mp4",
                                "X-Upload-Content-Length": str(size)})
        session = r.headers.get("location")
        if not session:
            raise YouTubeError(r.status, r.body, "videos.insert: no upload session")
        sent = 0
        with path.open("rb") as f:
            while True:
                chunk = f.read(CHUNK)
                end = sent + len(chunk) - 1
                resp = self.http("PUT", session, {
                    "Authorization": f"Bearer {self.token()}",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {sent}-{end}/{size}"}, chunk)
                if resp.status in (200, 201):
                    return str(resp.json()["id"])
                if resp.status != 308:
                    raise YouTubeError(resp.status, resp.body, "upload chunk")
                rng = resp.headers.get("range", f"bytes=0-{end}")
                sent = int(rng.split("-")[-1]) + 1
                f.seek(sent)

    def set_thumbnail(self, video_id: str, png: Path) -> None:
        self._call("thumbnails.set", "POST",
                   f"{UPLOAD}/thumbnails/set?videoId={video_id}&uploadType=media",
                   headers={"Content-Type": "image/png"}, raw=png.read_bytes())

    def add_to_playlist(self, playlist_id: str, video_id: str) -> None:
        self._call("playlistItems.insert", "POST", f"{API}/playlistItems?part=snippet",
                   body={"snippet": {"playlistId": playlist_id, "resourceId": {
                       "kind": "youtube#video", "videoId": video_id}}})

    def comment(self, channel_id: str, video_id: str, text: str) -> None:
        """Top-level comment from the channel. (The API cannot pin comments.)"""
        self._call("commentThreads.insert", "POST", f"{API}/commentThreads?part=snippet",
                   body={"snippet": {"channelId": channel_id, "videoId": video_id,
                                     "topLevelComment": {"snippet": {"textOriginal": text}}}})

    # ----- channel -----
    def my_channel(self) -> dict[str, Any]:
        r = self._call("channels.list", "GET",
                       f"{API}/channels?part=id,snippet,brandingSettings&mine=true")
        items = r.json().get("items", [])
        if not items:
            raise RuntimeError("authorized account has no YouTube channel")
        return dict(items[0])

    def update_branding(self, channel_id: str, branding: dict[str, Any]) -> None:
        self._call("channels.update", "PUT", f"{API}/channels?part=brandingSettings",
                   body={"id": channel_id, "brandingSettings": branding})

    def upload_banner(self, png: Path) -> str:
        r = self._call("channelBanners.insert", "POST",
                       f"{UPLOAD}/channelBanners/insert?uploadType=media",
                       headers={"Content-Type": "image/png"}, raw=png.read_bytes())
        return str(r.json()["url"])

    def list_playlists(self) -> dict[str, str]:
        r = self._call("playlists.list", "GET",
                       f"{API}/playlists?part=snippet&mine=true&maxResults=50")
        return {i["snippet"]["title"]: i["id"] for i in r.json().get("items", [])}

    def create_playlist(self, title: str, description: str) -> str:
        r = self._call("playlists.insert", "POST", f"{API}/playlists?part=snippet,status",
                       body={"snippet": {"title": title, "description": description},
                             "status": {"privacyStatus": "public"}})
        return str(r.json()["id"])

    def video_status(self, video_id: str) -> dict[str, Any]:
        r = self._call("videos.list", "GET", f"{API}/videos?part=status&id={video_id}")
        items = r.json().get("items", [])
        return dict(items[0]["status"]) if items else {}
