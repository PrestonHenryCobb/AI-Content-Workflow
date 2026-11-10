# One-time setup (the human 1%)

Everything else is automated. Do these once, in order. Later phases will add exact
click-paths as each integration is built.

| # | Step | Needed by phase | Done |
|---|---|---|---|
| 1 | Create a Google account + YouTube **brand** channel named **Cold Save**, handle **@coldsavefiles** (fallbacks in `docs/DECISIONS.md` D15); verify phone (unlocks custom thumbnails, >15 min uploads). Add a contact email on the About page (the description promises one for takedown requests) | 4 | ☐ |
| 1b | Upload `brand/art/profile_800.png`, `banner_2560x1440.png`, `watermark_150.png`; paste the description from `brand/channel_description.md`; add keywords from `brand/identity.yaml` (Phase 4 automates everything except the profile picture and banner, which the API can't set) | 4 | ☐ |
| 1c | Optional: run Actions → **brand-check** to confirm handle/domain availability | 2 | ☐ |
| 2 | Google Cloud project → enable YouTube Data API v3 + YouTube Analytics API → OAuth client (Desktop) | 4 | ☐ |
| 3 | Set the OAuth consent screen to **In production** (otherwise refresh tokens expire after 7 days) | 4 | ☐ |
| 4 | Run `uv run python scripts/auth_youtube.py` once to mint a refresh token (script ships in Phase 4) | 4 | ☐ |
| 5 | Submit the **YouTube API compliance audit** — until approved, API uploads are forced private | 4 | ☐ |
| 6 | Request a YouTube quota increase (default 10,000 units/day ≈ 6 uploads) | 4 | ☐ |
| 7 | On your own computer: install Claude Code, run `claude setup-token` (uses your Pro plan), save the token as GitHub secret `CLAUDE_CODE_OAUTH_TOKEN`. Do **not** add an `ANTHROPIC_API_KEY` secret | 3 | ☐ |
| 8 | fal.ai API key for Flux Schnell stills → GitHub secret `FAL_KEY` (optional: without it stills are procedural) | 3 | ☐ |
| 9 | Cloud bucket (Cloudflare R2 free tier recommended) + access keys | 5 | ☐ |
| 10 | Discord (or Slack) webhook URL for alerts | 5 | ☐ |
| 11 | Pick the channel name from the shortlist in `brand/name_shortlist.md` | 2 | ☑ Cold Save |
| 12 | TikTok developer app + Content Posting API audit | 8 | ☐ |
| 13 | Instagram Business account linked to a Facebook Page + Meta app | 8 | ☐ |
| 14 | Add every key from `.env.example` to GitHub → Settings → Secrets and variables → Actions | 5 | ☐ |
| 15 | Set repo **variable** `PIPELINE_ENABLED=true` | 5 | ☐ |

**GitHub Actions minutes:** a private repo gets 2,000 free minutes/month; Blender renders may
exceed that. A public repo has unlimited minutes (secrets stay secret either way).
