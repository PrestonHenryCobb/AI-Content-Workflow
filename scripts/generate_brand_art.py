"""Render the channel art set into brand/art/.

    uv run python scripts/generate_brand_art.py --name "Cold Save"
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pipeline import brand_art

OUT = Path(__file__).resolve().parent.parent / "brand" / "art"
TAGLINE = "NEW CASE EVERY 8 HOURS  -  FULL FILES EVERY SUNDAY"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    brand_art.profile_picture().save(a.out / "profile_800.png")
    brand_art.profile_picture().resize((98, 98)).save(a.out / "profile_98_preview.png")
    brand_art.banner(a.name, TAGLINE).save(a.out / "banner_2560x1440.png")
    brand_art.watermark().save(a.out / "watermark_150.png")
    brand_art.end_screen(a.name).save(a.out / "end_screen_1920x1080.png")
    brand_art.thumbnail_template("Vanished From Room 12", "CASE #0001").save(
        a.out / "thumbnail_example_1280x720.png")
    print(f"wrote art to {a.out}")


if __name__ == "__main__":
    main()
