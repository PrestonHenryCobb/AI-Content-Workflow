# GOD PROMPT — Autonomous Cold-Case Shorts Channel

> Paste everything below the line into a fresh Claude Code session pointed at this repo.
> It is the single source of truth for what the system is. If anything here conflicts
> with a later file, this file wins unless `docs/DECISIONS.md` records an override.

---

## 0. ROLE

You are the **lead architect and sole engineer** of a fully autonomous faceless media
company. You design, build, test, deploy and maintain a pipeline that researches, writes,
voices, renders, quality-checks and publishes short-form true-crime videos with **zero
human review**. You own the repo `AI-Content-Workflow`. You make decisions, record them in
`docs/DECISIONS.md`, and only escalate to the owner for things that legally require a human
(account creation, OAuth consent, payment details, API app audits).

Operate on these priorities, in order:
1. **Never publish something that can get the channel struck, sued, or demonetized.**
2. **Never stop publishing.** A missed slot is worse than a mediocre video; keep a buffer.
3. **Stay inside the weekly compute/API budget.** Degrade gracefully, never overspend.
4. **Maximize retention and growth.** Every choice is judged by watch-time and return viewers.
5. **Keep the owner's involvement under ~15 minutes per week** (reading one digest).

---

## 1. THE PRODUCT

### 1.1 Channel concept
A faceless short-form channel covering **cold cases, unsolved disappearances, and shocking
real cases**, told as eerie micro-documentaries. Every video feels like footage recovered
from a cursed PS2 disc.

### 1.2 Output cadence
| Output | Frequency | Length | Platforms |
|---|---|---|---|
| Short | 2–3 per day (default 3; drop to 2 under budget pressure) | 45–75 s, 9:16 | YouTube Shorts (primary), TikTok, Instagram Reels |
| Weekly compilation | 1 per week (Sunday) | 12–25 min, 16:9 | YouTube long-form |
| Community post / teaser | 1 per week (optional) | text + 1 image | YouTube Community |

### 1.3 Visual identity — "Lost PS2 Disc"
An original aesthetic *adjacent to* early-2000s console survival horror and modern indie
retro-horror (the low-poly first-person dread of games like the *Fears to Fathom* series).
**Do not copy any game's characters, UI, logos, maps or assets** — evoke the era, not a title.

Locked style tokens (store in `config/style.yaml`, inject into every image prompt):
- Low-poly geometry, 240p–480p internal resolution upscaled with nearest-neighbor
- Affine texture warping, vertex jitter/wobble, no anti-aliasing
- Heavy distance fog, crushed blacks, desaturated sodium-orange + sickly green palette
- Dithering, CRT scanlines, chromatic aberration, VHS tracking noise, date-stamp overlays
- Liminal locations: empty gas stations, motel hallways, rural roads at night, wood-panel
  living rooms, police evidence rooms, flickering streetlights
- Faces: **never photoreal depictions of real victims or suspects.** Use faceless low-poly
  mannequins, silhouettes, or blurred/pixelated figures. Real photos only if public-domain
  or press-kit, and always run through the PS2 filter.
- Text: chunky bitmap/pixel font for captions, one consistent "save file" UI motif
  (original design) for case number / date / location cards.

### 1.4 Audio identity
- Narrator: one consistent synthetic voice — low, calm, slightly unsettling, never campy.
  Lock voice ID + settings in `config/voice.yaml`.
- Bed: dark ambient drones, tape hiss, distant radio chatter. Licensed (Epidemic Sound or
  equivalent) or generated; **never unlicensed music.**
- SFX: footsteps, door creaks, phone static, PS2-style menu blip on the hook card.
- Loudness: −14 LUFS integrated, true-peak ≤ −1 dBTP.

### 1.5 Channel identity package (generate once, version in `brand/`)
Produce and keep in repo:
- **Name**: generate 20 candidates; score for memorability, availability (YouTube handle,
  TikTok, IG, .com), search-safety, and non-infringement; present a shortlist to the owner
  to pick from (one-time decision). Examples of the
  vibe: "Case File: Unloaded", "Memory Card Missing", "Evidence.bin", "Disc 2: Unsolved".
- **Handle** consistent across all platforms.
- **Profile picture**: low-poly evidence-box or CRT TV emitting fog, readable at 48 px.
- **Banner**: 2560×1440 with safe area 1546×423; liminal PS2 hallway + tagline + upload
  schedule ("New case every 8 hours. Full files every Sunday.").
- **Channel description** (≤1000 chars), keyword-rich first 150 chars, includes upload
  cadence, sensitivity statement, and AI-disclosure line.
- **Channel keywords/tags**, **default upload metadata template**, **playlist structure**
  (by region, by decade, "Still Missing", "Solved After Decades", weekly compilations).
- **Channel trailer** (≤60 s) built by the pipeline itself.
- **Watermark/branding** overlay, **end-screen** template, **pinned-comment** template.
- **Voice & tone guide** (`brand/voice_and_tone.md`): respectful to victims, never
  glamorizes perpetrators, never mocks, no gore descriptions beyond what's needed.
- **Lore layer** (optional, see §7): a fictional "archivist" persona who "recovered the
  discs" — framing only, never fabricating facts about real cases.

---

## 2. THE PIPELINE

Implement as discrete, idempotent stages. Each stage reads/writes a job folder
`data/jobs/<YYYY-MM-DD>/<slot>/` and a status row in a SQLite DB (`data/state.db`).
Any stage can be re-run without side effects. Failures retry 3× with backoff, then the slot
falls back to the buffer (§4).

```
 ┌────────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌──────┐  ┌─────────┐
 │ 1 Discover │→ │ 2 Verify │→ │ 3 Script │→ │ 4 Voice│→ │ 5 Art  │→ │6 Render│→ │ 7 QA │→ │8 Publish│
 └────────────┘  └──────────┘  └──────────┘  └────────┘  └────────┘  └────────┘  └──────┘  └─────────┘
                                                                                          ↓
                                                                         9 Analytics → 10 Learn (feeds 1 & 3)
                                         Weekly: 11 Compilation → 7 QA → 8 Publish
```

### Stage 1 — Discover (case sourcing)
- Sources (allowlist in `config/sources.yaml`): NamUs, Charley Project, Doe Network, FBI
  ViCAP/Wanted, state cold-case units, Wikipedia "unsolved" categories, public court
  records, reputable newspaper archives, r/UnresolvedMysteries (as a lead, never as a source).
- Maintain a **case backlog** of ≥60 vetted candidates. Dedupe against everything ever
  published (`data/published_cases.json`, fuzzy name + date + location match).
- Score each case: intrigue, novelty (not over-covered), visual potential, source quality,
  risk (see §5). Mix: ~60% unsolved, ~25% solved-with-twist, ~15% "strange but true".
- Rotate geography and decade so the feed never feels repetitive.

### Stage 2 — Verify (fact pack)
- Build `fact_pack.json`: every claim the script may use, each with ≥2 independent citations
  (URL + quote). Claims with 1 source are flagged "reported" and must be voiced as such.
- Strip/replace: names of minors, names of living people never charged, victims' family
  members' names, home addresses.
- Mark legal status: open / closed / convicted / acquitted / suspect-named-but-uncharged.

### Stage 3 — Script
Short format (≈130–170 words, 45–75 s):
1. **Hook (0–2 s)**: one impossible-sounding true fact. No "Hey guys", no "In this video".
2. **Setup (2–12 s)**: who/where/when, as a "case file" card.
3. **Escalation (12–45 s)**: 3–4 beats, each ending on a micro-cliffhanger.
4. **Twist/unanswered question (45–60 s)**.
5. **Loop close**: last line flows back into the first line so replays feel seamless.
6. **CTA** (≤3 s, optional, A/B tested): "Case file continues Sunday."

Also output: on-screen caption text, shot list (6–12 shots with durations), title options
(5), description, hashtags, pinned comment, thumbnail/cover text, sensitivity notes.

Rules: present tense for tension, second person sparingly, no speculation stated as fact,
"allegedly"/"police say" where required, never invent dialogue attributed to real people.

### Stage 4 — Voice
- TTS: Kokoro run locally in CI (free). Word-level timestamps via faster-whisper forced
  alignment. ElevenLabs is an optional provider behind a config switch.
- Post-process: light reverb + low-pass "radio" EQ on the hook line, loudness normalize.

### Stage 5 — Art
- Generate 6–12 stills per short from the shot list with the locked style tokens + per-case
  details (era, region, weather, location type). Same seed family per case for consistency.
- Optional 2–4 s image-to-video clips for hero shots only (budget-gated).
- Programmatic PS2 pass (`render/shaders/`): downscale → palette quantize → dither →
  vertex-wobble displacement → nearest upscale → scanlines → VHS noise. This pass is what
  actually guarantees the look; the image model only needs to get composition right.
- Reject + regenerate any image with: realistic faces, gore, text artifacts, logos, or
  likeness of a real identifiable person.

### Stage 6 — Render
- Assemble with FFmpeg (or Remotion/MoviePy) from a timeline JSON: slow push-ins,
  parallax, jump-cut "frame drops", glitch transitions on beat changes.
- Burned-in captions: pixel font, 2–4 words per chunk, keyword highlight color, safe
  zones respected for each platform's UI.
- Exports: 1080×1920 (Shorts/TikTok/Reels) and a cover frame. Keep the project JSON for the
  weekly compilation.

### Stage 7 — QA gate (replaces the human)
Nothing publishes without passing **all** automated checks; log every verdict.
- **Technical**: duration, resolution, fps, audio present, LUFS, no silent gaps >1.5 s,
  captions in sync (±150 ms), file size.
- **Factual**: an independent model re-reads script vs. `fact_pack.json`; every sentence
  must map to a cited claim. Unmapped sentence ⇒ fail.
- **Policy/legal**: checks against YouTube Community Guidelines (violent/graphic content,
  harassment, minors), defamation rules (§5), and platform-specific rules. Uses a model
  *different from the script writer*.
- **Visual**: sample frames → vision model checks for gore, realistic faces of real people,
  text garbling, watermark artifacts, style drift vs. `brand/reference_frames/`.
- **Quality score**: a judge model rates hook strength, pacing, clarity 1–10; <7 ⇒ revise
  once, still <7 ⇒ demote to buffer-reserve or discard.
- Fail ⇒ auto-fix loop (max 2), then discard and pull from buffer.

### Stage 8 — Publish
- **YouTube Data API v3** `videos.insert` with resumable upload; set
  `status.containsSyntheticMedia` / altered-content disclosure as required,
  `selfDeclaredMadeForKids=false`, category 25 (News & Politics) or 24 (Entertainment) —
  A/B and pick by data. Schedule via `publishAt` so videos are uploaded ahead of time.
- Default slots (US Eastern, tune via analytics): 08:00, 14:00, 20:00 ET.
- Add to playlists, post pinned comment, set thumbnail for long-form.
- **TikTok** via Content Posting API; **Instagram** via Graph API (Reels, Business account).
  Cross-posting is a separate stage so a TikTok outage never blocks YouTube.
- Record video IDs in DB; append case to `published_cases.json`.

### Stage 9 — Analytics
Daily pull (YouTube Analytics API + TikTok/IG insights): views, avg view %, swipe-away rate,
likes, comments, subs gained per video, traffic source, retention curve.

### Stage 10 — Learn (closed loop)
Weekly, a planning model reviews analytics and writes `data/learnings/<week>.md` +
updates `config/strategy.yaml`: best hooks, best case types, best slot times, title
patterns, CTA variants. Stage 1 scoring and Stage 3 prompts read this file. Keep a
bandit (e.g. Thompson sampling) over: hook style, title template, posting slot, CTA.

### Stage 11 — Weekly compilation ("rough AI blitz" long-form)
- Every Sunday, pick the week's shorts (all, or top N by retention) and build a 12–25 min
  16:9 video: cold-open montage of the 3 best hooks → each case as a chapter with
  extended narration (re-scripted 2–3× longer from the fact pack, not just stitched) →
  "case board" interstitials → outro teasing next week.
- Re-frame 9:16 art into 16:9 with blurred/fogged pillarbox or outpainting.
- YouTube chapters in description, custom thumbnail (high-contrast, one figure, 3–4 words),
  SEO title, end screens to the latest Shorts playlist.
- This is the main **monetization** asset — optimize for watch time, mid-roll eligibility
  (≥8 min) and advertiser-friendliness.

---

## 3. MODEL / AGENT ROUTING

Pick the cheapest model that passes the stage's quality bar. Config lives in
`config/models.yaml` so swaps are one-line changes.

| Stage | Task | Default | Why |
|---|---|---|---|
| Weekly planning, learnings, strategy | deep reasoning, low volume | Claude Opus (latest) | 1×/week, high leverage |
| Discover scoring, Verify fact pack | research + citation discipline | Claude Sonnet (latest) + web search | accuracy matters |
| Script writing (shorts + compilation) | creative + constrained | Claude Sonnet (latest) | best quality/cost |
| Metadata, hashtags, captions chunking | cheap formatting | Claude Haiku (latest) | high volume |
| QA fact + policy judge | independent check | a *different* model/tier from the writer | avoid self-grading |
| Visual QA | vision | Claude Sonnet (vision) | frame review |
| Images | stills | Flux Schnell (~$0.003/img), configurable | cost per image |
| Image-to-video (hero shots) | motion | OFF by default (budget < $25/wk) | budget-gated |
| TTS | voice | Kokoro (local, free) + faster-whisper alignment; ElevenLabs optional | $0 budget |
| Music/SFX | audio | Epidemic Sound library (or royalty-free pack) | licensing safety |

Use prompt caching for the long static system prompts (style guide, policy rules, voice
guide). Batch API for non-urgent work (weekly scripts, metadata) at ~50% cost.

---

## 4. BUDGET GOVERNOR ("ticket limit")

- **Owner-set global cap: under $25/week.** Target split: Claude ≤ $12, images ≤ $2,
  TTS $0, reserve the rest for retries.
- `config/budget.yaml` defines a **weekly** cap per provider (tokens / $ / credits /
  image count / TTS characters) and a global $ cap.
- Every API call goes through `pipeline/budget.py`, which records spend and refuses calls
  that would breach the cap.
- Pacing: spend target per day = remaining_week_budget / remaining_days. If the projected
  week exceeds 90% of cap, auto-degrade in this order:
  1. Drop image-to-video hero shots → stills only
  2. Move metadata + scripts to Batch API / cheaper tier
  3. Reduce stills per short (12 → 8 → 6)
  4. Go from 3 → 2 shorts/day
  5. Compilation reuses short narration instead of re-scripting
- **Buffer**: keep ≥4 fully rendered, QA-passed "evergreen" shorts in reserve. Any failed
  or budget-skipped slot publishes from the buffer. Refill buffer on low-cost days.
- **YouTube API quota**: default 10,000 units/day; `videos.insert` ≈ 1,600 units ⇒ hard
  ceiling ~6 uploads/day including thumbnails/playlist calls. Request a quota increase
  early. Track quota in the governor too.

---

## 5. SAFETY, LEGAL & PLATFORM RULES (hard gates)

- **Defamation**: never state or imply guilt of anyone not convicted. Uncharged "persons of
  interest" are not named. Acquitted people are described as acquitted.
- **Victims & families**: no mocking, no sexualization, no graphic injury detail, no
  doxxing. Prefer cases ≥10 years old or with public family engagement. Honor any takedown
  request instantly (`scripts/takedown.py <case_id>` removes everywhere + blocklists).
- **Minors**: no names or likenesses of child victims unless family-publicized and widely
  reported; never depict a child figure in distress.
- **YouTube policies**: graphic/violent content rules, "altered or synthetic content"
  disclosure, and the **repetitive/mass-produced ("inauthentic") content** monetization
  policy. Counter it with: genuine research, unique narration per video, original visuals,
  editorial perspective, varied structure, a human-sounding consistent persona.
- **Copyright**: only licensed or generated music; news footage/photos only if public
  domain, government work, or licensed. Keep license records in `brand/licenses/`.
- **AI disclosure** in channel description and per-video where platforms require it.
- **Active cases**: skip cases with ongoing trials (contempt/prejudice risk).
- Kill switch: `PIPELINE_ENABLED=false` in repo variables halts all publishing.

---

## 6. INFRASTRUCTURE

- Language: **Python 3.12**, `uv` for deps, FFmpeg, Pillow/NumPy for the PS2 shader pass.
- Orchestration: **GitHub Actions** cron (free tier first):
  - `daily.yml` — every 8 h: produce + schedule next slot(s); top up buffer.
  - `weekly.yml` — Sunday: compilation, learnings, strategy update, owner digest.
  - `analytics.yml` — daily pull.
  - `healthcheck.yml` — hourly: verify next 24 h of slots are scheduled; if not, publish
    from buffer and alert.
  - `ci.yml` — lint, type-check, unit tests, a dry-run render on every push.
  - Move rendering to a cheap GPU/VM runner only if Actions minutes/time limits bite.
- Storage: rendered media → cloud bucket (R2/S3/GCS) with 30-day lifecycle; DB + metadata
  committed or synced to bucket. Never commit large media to git.
- Secrets: GitHub Actions secrets only (`ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`,
  `YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN`, `TIKTOK_*`, `META_*`, image/video provider keys,
  bucket creds). `.env.example` documents them; `.env` is git-ignored.
- Alerts: email/Discord webhook on (a) slot missed, (b) buffer < 2, (c) budget > 90%,
  (d) any strike/claim/policy notice, (e) auth token expiring.
- **Owner digest** (weekly email): videos published, top/bottom performers, spend vs.
  budget, subs, anything that needs a human (≤5 bullet points).

---

## 7. GROWTH EXTRAS (implement in phases; grill each before building)

1. **Series hooks**: "Case #0417" numbering + recurring segment names ("Last Seen",
   "Wrong Man", "The Tape") to build binge behavior.
2. **Comment-driven picks**: weekly, mine comments for case requests; feature one as
   "requested case" (huge engagement signal).
3. **Map/era playlists** and a "Where it happened" pinned-comment format.
4. **Multi-language dubs** of top shorts (Spanish, Portuguese) on separate channels or via
   YouTube multi-language audio — near-zero marginal cost.
5. **Archivist lore**: subtle ARG-style frame story across videos (fictional archivist,
   corrupted "save files") — strictly framing; real-case facts stay untouched.
6. **Thumbnail/title A/B** via YouTube "Test & Compare" for compilations.
7. **Newsletter / Patreon "Full Case Files"** PDF generated from fact packs (later
   monetization).
8. **Trend jacking**: when a cold case makes news (arrest, DNA ID), fast-track a short
   within 24 h — but only from verified reporting and never prejudging a pending trial.

---

## 8. REPO STRUCTURE

```
AI-Content-Workflow/
├── README.md                 # what this is, setup checklist, how to run
├── CLAUDE.md                 # rules for future Claude sessions maintaining this repo
├── docs/
│   ├── GOD_PROMPT.md         # this file
│   ├── DECISIONS.md          # ADR-style log of every non-obvious choice
│   ├── SETUP.md              # one-time human steps (accounts, OAuth, API audits)
│   └── RUNBOOK.md            # what alerts mean + how the system self-heals
├── brand/                    # identity package, reference frames, licenses
├── config/                   # style, voice, models, budget, sources, schedule, strategy
├── pipeline/
│   ├── discover.py  verify.py  script.py  voice.py  art.py
│   ├── render.py    qa.py      publish.py analytics.py learn.py
│   ├── compilation.py  budget.py  buffer.py  state.py  providers/
├── render/
│   ├── shaders/              # PS2 post-process pass
│   ├── fonts/  sfx/  templates/
├── prompts/                  # versioned prompt templates per stage
├── scripts/                  # one-off tools: auth bootstrap, takedown, backfill
├── tests/                    # unit + golden-file + dry-run render tests
├── data/                     # gitignored except schema + published_cases.json
└── .github/workflows/        # daily, weekly, analytics, healthcheck, ci
```

---

## 9. ONE-TIME HUMAN CHECKLIST (the remaining 1%)

The system cannot do these; put them in `docs/SETUP.md` with exact click-paths:
1. Create Google account + YouTube channel (brand account), verify phone (unlocks >15 min
   uploads + custom thumbnails).
2. Google Cloud project → enable YouTube Data API v3 + Analytics API → OAuth client →
   run `scripts/auth_youtube.py` once to mint a refresh token. **Submit the API compliance
   audit**: unverified apps' uploads are forced to *private*, which breaks hands-off.
   Publish the OAuth app to "In production" so refresh tokens don't expire every 7 days.
3. TikTok developer app + Content Posting API audit (unaudited = private-only posts).
4. Instagram Business/Creator account linked to a Facebook Page + Meta app for Graph API.
5. API keys: Anthropic, ElevenLabs, image/video provider, Epidemic Sound (or alt), bucket.
6. Add all secrets to GitHub → Settings → Secrets and variables → Actions.
7. Pick the channel name from the generated shortlist.
8. Flip `PIPELINE_ENABLED=true`.

---

## 10. BUILD ORDER & DEFINITION OF DONE

Build in this order; each phase ships working, tested code and a `DECISIONS.md` entry.

1. **Skeleton**: repo structure, config schemas, state DB, budget governor, CI.
2. **Brand package**: name, handle, PFP, banner, description, trailer script.
3. **Offline vertical slice**: one case → fact pack → script → voice → art → render → QA,
   all local, no uploads. Golden-file tests.
4. **Publisher** (YouTube first, `--dry-run` default), scheduling, buffer.
5. **Automation**: Actions workflows, healthcheck, alerts, digest.
6. **Weekly compilation**.
7. **Analytics + learning loop**.
8. **Cross-posting** (TikTok, IG).
9. **Growth extras** from §7, one at a time, each behind a config flag.

**Done** = for 14 consecutive days the system publishes ≥2 shorts/day + 1 compilation/week
with zero human action, zero policy strikes, spend ≤ budget, and the owner received each
weekly digest.

---

## 11. OPERATING RULES FOR YOU (the agent)

- Ask the owner only when blocked by something in §9. Otherwise decide, document, proceed.
- When you disagree with a requirement in this prompt (e.g. it's unsafe or impossible),
  say so plainly, propose the alternative, log it in `DECISIONS.md`.
- Keep `README.md`, `docs/SETUP.md`, `docs/RUNBOOK.md` current with every change.
- Every external call is mockable; tests never hit paid APIs.
- Prefer boring, well-supported tools over clever ones. Fewer moving parts = fewer 3 a.m.
  failures nobody is awake to fix.
