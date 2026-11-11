# One-time setup (the human 1%)

Everything else is automated. Do these once, in order. Later phases will add exact
click-paths as each integration is built.

| # | Step | Needed by phase | Done |
|---|---|---|---|
| 1 | Create a Google account + YouTube **brand** channel named **Cold Save**, handle **@coldsavecases** (DECISIONS D41); verify phone (unlocks custom thumbnails, >15 min uploads). Add a contact email on the About page (the description promises one for takedown requests) | 4 | ☐ |
| 1b | YouTube Studio → Customization: upload `brand/art/profile_800.png` (profile picture) and `brand/art/watermark_150.png` (Branding → video watermark). The API can't set these two; step 4b does the rest | 4 | ☐ |
| 1c | Optional: run Actions → **brand-check** to confirm handle/domain availability | 2 | ☐ |
| 2 | Google Cloud project + OAuth client: see **Step 4 walkthrough** below | 4 | ☐ |
| 3 | Publish the OAuth app to **In production** *before* minting the token (Testing-mode refresh tokens expire after 7 days) | 4 | ☐ |
| 4 | Mint the refresh token in OAuth Playground (no install): see **Step 4 walkthrough** below → secret `YOUTUBE_REFRESH_TOKEN` | 4 | ☐ |
| 4b | Actions → **channel-setup** with *apply* checked | 4 | ☑ done 2026-11-11 |
| 5 | Submit the **YouTube API audit + quota request** using the copy-paste answers in `docs/API_AUDIT.md`. Until it is approved, API uploads are forced private | 4 | ☐ |
| 6 | Quota increase: included in the same form (20,000 units/day), see `docs/API_AUDIT.md` | 4 | ☐ |
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

## Step 4a: public pages for Google's Branding page and the API audit

1. Repo **Settings → Pages** → *Build and deployment* → Source: **GitHub Actions**.
2. Actions → **pages** → Run workflow (it also runs on any change to `site/`).
3. The site is then at `https://prestonhenrycobb.github.io/AI-Content-Workflow/` with
   `privacy.html` and `terms.html`.
4. Google Cloud → **Google Auth Platform → Branding**:
   - App name: `Cold Save Pipeline` · User support email: your email
   - App logo: **leave empty** (uploading a logo requires Google's brand verification)
   - Application home page: `https://prestonhenrycobb.github.io/AI-Content-Workflow/`
   - Privacy policy: `https://prestonhenrycobb.github.io/AI-Content-Workflow/privacy.html`
   - Terms of service: `https://prestonhenrycobb.github.io/AI-Content-Workflow/terms.html`
   - Authorized domains: `prestonhenrycobb.github.io`
   - Developer contact: your email → Save
5. **Audience → Publish app** (status *In production*).

## Step 4 walkthrough: YouTube API access (browser only)

1. [console.cloud.google.com](https://console.cloud.google.com) → project picker → **New project** → name `cold-save` → Create, then select it.
2. **APIs & Services → Library** → enable **YouTube Data API v3**, then **YouTube Analytics API**.
3. **Google Auth Platform** (or "OAuth consent screen") → Get started → app name `Cold Save Pipeline`, your email as support and contact → audience **External** → Create.
4. **Audience** → **Publish app** → confirm (status: *In production*). Unverified is fine for your own account; Google shows a warning screen you can click past.
5. **Clients** → **Create client** → type **Web application** → name `cold-save-github` → under *Authorized redirect URIs* add `https://developers.google.com/oauthplayground` → Create. Copy the **Client ID** and **Client secret** into GitHub secrets `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET`.
6. [developers.google.com/oauthplayground](https://developers.google.com/oauthplayground) → gear icon (top right) → tick **Use your own OAuth credentials** → paste the client ID and secret.
7. In *Step 1* on the left, type these four scopes into the box (one at a time, then **Authorize APIs**):
   `https://www.googleapis.com/auth/youtube.upload`
   `https://www.googleapis.com/auth/youtube`
   `https://www.googleapis.com/auth/youtube.force-ssl`
   `https://www.googleapis.com/auth/yt-analytics.readonly`
8. Sign in → **choose the Cold Save channel** (not your personal one) → "Google hasn't verified this app" → **Advanced → Go to Cold Save Pipeline** → allow all.
9. *Step 2* → **Exchange authorization code for tokens** → copy the **Refresh token** → GitHub secret `YOUTUBE_REFRESH_TOKEN`.
10. Afterwards, gear icon → untick "Use your own OAuth credentials" (the playground doesn't keep your token).
