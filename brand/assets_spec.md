# Platform asset specs

| Asset | File | Size | Notes |
|---|---|---|---|
| Profile picture | art/profile_800.png | 800×800 | shown as a circle down to 98 px; TV centred for the crop |
| Banner | art/banner_2560x1440.png | 2560×1440 | text inside the 1546×423 safe area |
| Watermark | art/watermark_150.png | 150×150 | transparent PNG, YouTube "branding watermark" |
| End screen bg | art/end_screen_1920x1080.png | 1920×1080 | right half left clear for YouTube elements |
| Compilation thumbnail | generated per video | 1280×720 | template: art/thumbnail_example_1280x720.png |
| TikTok / IG avatar | art/profile_800.png | reuse | |

Regenerate everything: `uv run python scripts/generate_brand_art.py --name "<Name>"`
