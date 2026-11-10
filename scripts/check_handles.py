"""Best-effort availability check for shortlisted names.

YouTube handle: GET youtube.com/@handle -> 404 means probably free.
.com domain:    RDAP lookup -> 404 means unregistered.
TikTok/Instagram block automated checks; claim those by hand.
Runs in GitHub Actions (brand-check workflow); this dev container's network blocks these hosts.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHORTLIST = ROOT / "brand" / "name_shortlist.md"
OUT = ROOT / "brand" / "handle_check.md"
UA = {"User-Agent": "Mozilla/5.0 (compatible; brand-check)"}


def status(url: str) -> int:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return int(e.code)
    except (urllib.error.URLError, TimeoutError):
        return -1


def verdict(code: int) -> str:
    return {404: "free", 200: "taken"}.get(code, f"unknown ({code})")


def parse_shortlist(text: str) -> list[tuple[str, str]]:
    rows = []
    for m in re.finditer(r"^\| \d+ \| \**([^|*]+?)\** \| @(\w+) \|", text, re.M):
        rows.append((m.group(1).strip(), m.group(2)))
    return rows


def main() -> None:
    rows = parse_shortlist(SHORTLIST.read_text())
    lines = ["# Handle check (auto-generated)", "",
             "| Name | YouTube @handle | .com domain |", "|---|---|---|"]
    for name, handle in rows:
        yt = verdict(status(f"https://www.youtube.com/@{handle}"))
        dom = verdict(status(f"https://rdap.org/domain/{handle}.com"))
        lines.append(f"| {name} | @{handle}: {yt} | {handle}.com: {dom} |")
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
