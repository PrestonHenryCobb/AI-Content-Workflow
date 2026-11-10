"""One-time: mint a YouTube refresh token for the pipeline (SETUP step 4).

Run on YOUR computer (needs a browser):
    YOUTUBE_CLIENT_ID=... YOUTUBE_CLIENT_SECRET=... python scripts/auth_youtube.py
Sign in with the Google account that owns the Cold Save channel (pick the brand
channel when asked). Copy the printed refresh token into the GitHub secret
YOUTUBE_REFRESH_TOKEN. Stdlib only, nothing to install.
"""

from __future__ import annotations

import http.server
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
PORT = 8765


def main() -> None:
    cid, secret = os.environ.get("YOUTUBE_CLIENT_ID"), os.environ.get("YOUTUBE_CLIENT_SECRET")
    if not cid or not secret:
        sys.exit("Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET (Desktop OAuth client).")
    redirect = f"http://127.0.0.1:{PORT}"
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",
        "state": state})
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            result.update(q)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and return to the terminal.")

        def log_message(self, *args: object) -> None:
            pass

    print("Opening browser. If it doesn't open, visit:\n", url)
    webbrowser.open(url)
    with http.server.HTTPServer(("127.0.0.1", PORT), Handler) as srv:
        while "code" not in result and "error" not in result:
            srv.handle_request()
    if result.get("state") != state or "code" not in result:
        sys.exit(f"Authorization failed: {result.get('error', 'state mismatch')}")
    body = urllib.parse.urlencode({
        "code": result["code"], "client_id": cid, "client_secret": secret,
        "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body)) as r:
        tok = json.loads(r.read())
    if "refresh_token" not in tok:
        sys.exit("No refresh token returned. Remove the app's access at "
                 "myaccount.google.com/permissions and run again.")
    print("\nYOUTUBE_REFRESH_TOKEN (add as a GitHub secret, keep it private):\n")
    print(tok["refresh_token"])


if __name__ == "__main__":
    main()
