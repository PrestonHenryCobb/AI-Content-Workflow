# One-time setup (the human 1%)

Everything else is automated. Do these once, in order. Later phases will add exact
click-paths as each integration is built.

| # | Step | Needed by phase | Done |
|---|---|---|---|
| 1 | Create a Google account + YouTube **brand** channel named **Cold Save**, handle **@coldsavefiles** (fallbacks in `docs/DECISIONS.md` D15); verify phone (unlocks custom thumbnails, >15 min uploads). Add a contact email on the About page (the description promises one for takedown requests) | 4 | ☐ |
| 1b | YouTube Studio → Customization: upload `brand/art/profile_800.png` (profile picture) and `brand/art/watermark_150.png` (Branding → video watermark). The API can't set these two; step 4b does the rest | 4 | ☐ |
| 1c | Optional: run Actions → **brand-check** to confirm handle/domain availability | 2 | ☐ |
| 2 | [console.cloud.google.com](https://console.cloud.google.com) → New project → APIs & Services → Library → enable **YouTube Data API v3** and **YouTube Analytics API** → OAuth consent screen (External; add your Google account as a test user for now) → Credentials → Create credentials → OAuth client ID → **Desktop app**. Save the client ID and secret as GitHub secrets `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` | 4 | ☐ |
| 3 | Set the OAuth consent screen to **In production** (otherwise refresh tokens expire after 7 days) | 4 | ☐ |
| 4 | On your computer: `YOUTUBE_CLIENT_ID=… YOUTUBE_CLIENT_SECRET=… python scripts/auth_youtube.py` → sign in, choose the Cold Save brand channel → save the printed token as GitHub secret `YOUTUBE_REFRESH_TOKEN` | 4 | ☐ |
| 4b | `uv run python scripts/setup_channel.py --apply` (with the three YOUTUBE_* vars set) → sets description, keywords, banner, creates playlists, writes `config/youtube_ids.json`; commit that file | 4 | ☐ |
| 5 | Submit the **YouTube API compliance audit** — until approved, API uploads are forced private | 4 | ☐ |
| 6 | Request a YouTube quota increase (default 10,000 units/day ≈ 6 uploads) | 4 | ☐ |
| 7 | On your own computer: install Claude Code, run `claude setup-token` (uses your Pro plan), save the token as GitHub secret `CLAUDE_CODE_OAUTH_TOKEN`. Do **not** add an `ANTHROPIC_API_KEY` secret | 3 | ☐ |
| 8 | fal.ai API key for Flux Schnell stills → GitHub secret `FAL_KEY` (optional: without it stills are procedural) | 3 | ☐ |
| 9 | ~~Cloud bucket~~ not needed: state lives on a `state` branch and a `buffer` release (DECISIONS D27) | 5 | ☑ |
| 10 | Alerts arrive as GitHub issues (emailed to you automatically). Optional: Discord/Slack webhook as secret `ALERT_WEBHOOK_URL` | 5 | ☐ |
| 11 | Pick the channel name from the shortlist in `brand/name_shortlist.md` | 2 | ☑ Cold Save |
| 12 | TikTok (optional): [developers.tiktok.com](https://developers.tiktok.com) → create app → add **Content Posting API** (Direct Post) → get client key/secret → authorize your TikTok account once to get a refresh token → secrets `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN` → set `tiktok.enabled: true` in `config/crosspost.yaml`. Posts are private (SELF_ONLY) until TikTok approves the app audit; then set `privacy_level: PUBLIC_TO_EVERYONE` | 8 | ☐ |
| 13 | Instagram (optional): switch the IG account to Professional (Creator or Business) and link a Facebook Page → [developers.facebook.com](https://developers.facebook.com) → app with Instagram Graph API → in Business Settings create a **System User** with the IG account as an asset and generate a token (doesn't expire) with `instagram_basic`, `instagram_content_publish`, `pages_show_list` → secrets `META_IG_USER_ID`, `META_ACCESS_TOKEN` → set `instagram.enabled: true` in `config/crosspost.yaml` | 8 | ☐ |
| 14 | Add every key from `.env.example` to GitHub → Settings → Secrets and variables → Actions | 5 | ☐ |
| 15 | When steps 1–8 are done: Settings → Secrets and variables → Actions → **Variables** → New: `PIPELINE_ENABLED` = `true`. This turns on the nightly, healthcheck and weekly schedules and real uploads | 5 | ☐ |
| 16 | Recommended first: Actions → **nightly** → Run workflow with *dry run* checked, and look at the result before step 15 | 5 | ☐ |

**GitHub Actions minutes:** a private repo gets 2,000 free minutes/month. Estimated use:
nightly ~40–70 min × 30 + healthcheck ~2 min × 180 + weekly ≈ **1,600–2,500 min/month**, which
may go over. Options: make the repo public (unlimited minutes; secrets stay secret, and
the code contains nothing private), or set `shorts_per_day: 2`. The weekly digest will
show if you're close.
