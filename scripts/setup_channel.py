"""Apply the Cold Save identity to the YouTube channel (idempotent).

Sets the channel description, keywords and country, uploads the banner, creates the
playlists from brand/identity.yaml, and writes channel/playlist ids to
config/youtube_ids.json for the publisher. The profile picture and the branding
watermark can't be set through the API; upload those by hand (SETUP step 1b).

    uv run python scripts/setup_channel.py            # dry run: prints what it would do
    uv run python scripts/setup_channel.py --apply    # needs YOUTUBE_* secrets
"""

from __future__ import annotations

import argparse
import json
import re

import yaml

from pipeline.budget import Governor
from pipeline.config import REPO_ROOT, load_settings
from pipeline.state import State
from pipeline.youtube import Credentials, YouTube

BRAND = REPO_ROOT / "brand"
IDS = REPO_ROOT / "config" / "youtube_ids.json"


def channel_description() -> str:
    text = (BRAND / "channel_description.md").read_text()
    m = re.search(r"```\n(.*?)```", text, re.S)
    if not m:
        raise ValueError("channel description block not found")
    return m.group(1).strip()


def keywords_string(words: list[str]) -> str:
    return " ".join(f'"{w}"' if " " in w else w for w in words)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    ident = yaml.safe_load((BRAND / "identity.yaml").read_text())
    desc = channel_description()
    kw = keywords_string(ident["keywords"])
    playlists = ident["playlists"]
    print(f"Channel: {ident['name']} ({ident['handle']})")
    print(f"Description: {len(desc)} chars\nKeywords: {kw}")
    print("Playlists:", ", ".join(p["title"] for p in playlists))
    try:
        yt = YouTube(Credentials.from_env(), Governor(State(), load_settings()))
    except RuntimeError as e:
        print(f"\n{e}")
        if a.apply:
            raise
        print("(dry run without credentials: nothing checked)")
        return
    ch = yt.my_channel()     # read-only, 1 quota unit: proves the token works
    snip = ch.get("snippet", {})
    print(f"\nSigned in to channel: {snip.get('title')!r} {snip.get('customUrl', '')} "
          f"(id {ch['id']})")
    if snip.get("customUrl", "").lower().lstrip("@") != ident["handle"].lower().lstrip("@"):
        print(f"WARNING: expected {ident['handle']}. Did you pick the right channel when "
              "authorizing? If not, mint the refresh token again and choose Cold Save.")
    if not a.apply:
        print("(dry run: nothing changed; run with apply checked to update the channel)")
        return
    branding = ch.get("brandingSettings", {})
    branding.setdefault("channel", {}).update(
        {"description": desc, "keywords": kw, "country": "US", "defaultLanguage": "en"})
    banner = BRAND / "art" / "banner_2560x1440.png"
    if banner.exists():
        branding.setdefault("image", {})["bannerExternalUrl"] = yt.upload_banner(banner)
    yt.update_branding(ch["id"], branding)
    existing = yt.list_playlists()
    ids = {}
    for p in playlists:
        ids[p["title"]] = existing.get(p["title"]) or yt.create_playlist(
            p["title"], p.get("desc") or f"{ident['name']}: {p['title']}")
    IDS.write_text(json.dumps({"channel_id": ch["id"], "playlists": ids}, indent=2))
    print(f"Done. Wrote {IDS.relative_to(REPO_ROOT)}; commit it so the publisher can use it.")


if __name__ == "__main__":
    main()
