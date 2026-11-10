# Decisions & Open Questions

## Decided (2026-11-10)
- **D1. YouTube is the primary target; TikTok/IG cross-posting is a separate, non-blocking stage.**
- **D2. The "no human review" requirement is met by an automated QA gate** (fact, policy,
  visual, technical, quality) run by a different model from the script writer, plus a
  pre-rendered buffer so failures never cause a missed slot.
- **D3. The art style evokes the PS2/indie retro-horror era without copying any specific game.**
  The look comes mostly from a programmatic post-process pass, so it stays consistent
  whichever image model is used.
- **D4. GitHub Actions cron is the orchestrator**, starting on the free tier.
- **D5. A weekly budget governor sits in front of every paid API call** and degrades output
  in a fixed order before it would overspend.
- **D6. Weekly budget: under $25/week total** (owner, 2026-11-10). Image-to-video clips are
  off by default. *Superseded in part by D14:* Claude now runs on the subscription, so the
  dollar cap is $5/week for images + retries.
- **D7. Channel name: the pipeline generates ~20 candidates and checks handle availability;
  the owner picks from the shortlist.**
- **D8. Posting timezone: US Eastern.** Slots start at 08:00 / 14:00 / 20:00 ET and are
  tuned later by analytics.
- **D9. Voice: free local TTS (Kokoro) running inside GitHub Actions.** Word timestamps come
  from a local alignment pass (e.g. faster-whisper). The eerie tone comes from
  post-processing (pitch down slightly, EQ, reverb, tape hiss) to make up for the plainer
  base voice. ElevenLabs stays as an optional config switch if budget grows.
- **D10. Images: Flux Schnell (~$0.003/image)** via a pay-per-use API, at 6–8 stills per short.
- **D11. Animation at $0** (owner, 2026-11-10): 2.5D depth parallax on every still,
  procedural low-poly Blender scenes for 2–3 hero shots per short, a free ambient FX layer,
  and a reusable clip library. Paid image-to-video is a config switch, off by default.
- **D12. Budget split** *(revised by D14)*: Anthropic $0 (subscription), images $3, TTS $0,
  video $0, shared reserve $2, global $5. A provider past its cap borrows from reserve; the global cap is hard.
  The degradation ladder turns on one rung per 5% that projected spend overshoots 90% of cap.
- **D13. Model routing:** Sonnet 5.5 writes, Opus 5.5 checks facts (a different model, so
  nothing grades its own work), Haiku 5.5 does metadata, policy pre-screen and Blender
  scene specs, Opus 5.5 does weekly planning. Every Opus stage falls back to Sonnet 5.5.
- **D14. Claude runs on the owner's Claude Pro subscription, not API billing** (owner,
  2026-11-10). Every call is `claude -p` via `pipeline/llm.py`, authenticated with
  `CLAUDE_CODE_OAUTH_TOKEN`. API-key env vars are stripped from the child process so the
  pipeline can't fall into paid billing by accident; config validation rejects a non-zero
  Anthropic dollar cap while the subscription backend is active.
  Subscription pacing: generation only runs 01:00–06:00 ET; caps of 40/run, 45/day,
  220/week calls; on a plan-limit hit, 5 h cooldown and the weekly cap shrinks 10%
  (floor 120). The API backend stays a disabled option, used only if the owner opts in.
- **D15. Channel name: Cold Save, handle @coldsavefiles** (owner, 2026-11-10). Backups:
  Unmarked Disc, Memory Card Missing. If @coldsavefiles is taken, try @coldsave,
  @coldsavearchive, @coldsavecases in that order.
- **D16. Channel art is procedural, not image-model generated:** low-poly hallway and
  CRT TV drawn in code, then the PS2 post-process pass (`pipeline/fx/ps2.py`). $0, fully
  original, regenerable with one command. The same PS2 pass will be applied to every video
  frame. Pixel text uses Pillow's built-in bitmap font, so there's no font license to track.

- **D17. Hero "scene3d" shots use a built-in Python low-poly renderer, not Blender (for now).**
  `pipeline/scenes.py` projects flat-shaded polygons with distance fog at 360x640; every
  frame renders in milliseconds on a CI CPU, so there's real 3D camera motion with no Blender
  install or render minutes. Templates: hallway, night_road, room. Blender stays the upgrade
  path for scenes this renderer can't express. The clip library therefore stores only clips
  that are expensive to make (paid image-to-video, future Blender renders); procedural shots
  are cheaper to re-render than to decode.
- **D18. Fewer Claude calls per short (Pro limits):** metadata (titles, hashtags, pinned
  comment) comes from the script call; the separate metadata stage is reserved for the
  weekly compilation. Text gates (fact + policy) run *before* voice/art/render, so a
  rejected script costs no render time. Typical short: verify 1, script 1, fact 1,
  policy 1, visual 1, plus ~0.2 discover = **~5–6 calls**, up to ~10 with rewrites.
- **D19. Offline mode uses a clearly fictional fixture case** (example.org sources,
  "TEST CASE (fictional)" in every line) so CI can exercise the full render chain without
  network or subscription usage, and without anyone writing invented "facts" about a real case.
- **D20. Captions never show a fake date stamp.** The overlay shows REC + case number only,
  so nothing implies the visuals are real footage.
- **D21. Ambient audio bed is generated** (brown noise, low hum, static burst), so there's no
  music licensing in v1. A licensed library (e.g. Epidemic Sound) can replace it later.
- **D22. The slice runs in GitHub Actions**, because the dev container's network blocks research
  sites, Hugging Face (Kokoro weights) and fal.ai. Media deps (CPU torch, Kokoro,
  faster-whisper) install in the workflow and stay out of `uv.lock`.

- **D23. Publishing = upload ahead as private + `publishAt`** (DECISIONS-safe scheduling):
  each video goes public at its slot even if no job is running then. Every upload sets
  `containsSyntheticMedia: true` (YouTube's altered/synthetic content disclosure) and
  `selfDeclaredMadeForKids: false`. Live upload requires both `--live` and
  `PIPELINE_ENABLED=true`; otherwise a `publish_plan.json` is written.
- **D24. API limits accepted:** the YouTube API can't pin comments, set the profile picture,
  or (without multipart upload) set the watermark. The channel comment is posted unpinned;
  profile picture and watermark are one-time manual steps (SETUP 1b).
- **D25. Slot filling:** the freshest QA-passed video from the last 24 h goes first;
  otherwise the oldest buffered one, so the reserve never goes stale. A failed upload stays
  in the buffer and the other slots continue.
- **D26. YouTube client is stdlib HTTP** (resumable upload, token refresh), not the Google
  SDK: fewer dependencies, injectable transport, fully mock-tested, and every call is
  charged to the quota governor before it's made.

- **D27. State persists in GitHub itself, no cloud bucket:** `scripts/state.sh` saves the
  SQLite DB, published list and buffered jobs' JSON to an orphan `state` branch (one
  force-pushed commit, so no history bloat) and buffered videos to a `buffer` GitHub
  Release (assets deleted once used). This removes SETUP's bucket step. All scheduled
  workflows share one concurrency group, so they never race on state.
- **D28. Alerts and the weekly digest are GitHub issues** (labels `alert` / `digest`), which
  GitHub emails to the owner. Repeat alerts comment on the open issue instead of opening
  new ones. A Discord/Slack webhook (`ALERT_WEBHOOK_URL`) is optional.
- **D29. Schedules:** nightly 06:17 UTC (01:17 EST / 02:17 EDT, inside the Claude window),
  healthcheck every 4 h at :43, weekly Sunday 16:41 UTC. Scheduled runs do nothing unless
  repo variable `PIPELINE_ENABLED=true`; manual runs default to dry-run. Healthcheck is
  every 4 h, not hourly, to save Actions minutes.

- **D30. Weekly compilation:** best 3–8 QA-passed shorts of the week (by quality score),
  each expanded into a 2–3 min chapter (280–500 words) by Sonnet and re-fact-checked by Opus;
  if expansion fails lint or the fact check twice, that chapter falls back to the short's own
  script, so the compilation still ships. Cold open = the 3 strongest hooks (already
  fact-checked); outro has no factual claims. Rendered 1920x1080 at 24 fps (fewer frames
  to render) with no new image spend (scene templates + the shorts' stills). Built Sunday
  00:11 EST / 01:11 EDT, scheduled public Sunday 12:00 ET. Costs about 9–25 Claude calls a week.
- **D31. Compilation length:** hard minimum 3 min (so a thin week still ships), max 40.
  `midroll_eligible` (≥ 8 min) is recorded in compilation_meta.json; a normal week with
  6–8 expanded chapters runs about 14–22 min.
- **D32. Audio mastering:** loudnorm two-pass to -14 LUFS, then a -2 dBFS limiter because
  AAC encoding overshoots true peak. Check range: -16.5 to -12.5 LUFS, true peak ≤ -1 dBTP.
  (YouTube only turns loud videos down, so slightly quiet is harmless.) The limiter runs at
  192 kHz (approximate true-peak limiting), and after every render `enforce_true_peak`
  measures the encoded file and re-encodes only the audio, lowering gain until true peak
  ≤ -1.2 dBTP. That holds across FFmpeg builds; the CI runner's build overshot where the
  dev container's didn't.

- **D33. Learning loop:** daily analytics pull (videos 2–28 days old; YouTube Analytics has
  its own quota). Success = average % viewed ≥ the median of all measured videos. Thompson
  sampling (Beta(1,1) priors) chooses the **hook style** (impossible fact / last known /
  wrong detail / countdown) and **CTA** per short, so new options keep getting explored.
  Weekly, Opus reads the numbers and returns insights, a target case mix (moves ≤ 0.15 per
  week, each type kept between 10% and 75%) and ≤ 5 writer style notes. All of it lives in the state DB,
  not the code branch. Style notes are appended under "never override the hard rules".
  Slot times are *not* auto-changed; the digest shows the data and the owner decides.

- **D34. Cross-posting runs after the YouTube slot** (TikTok and Instagram APIs have no
  publishAt): `crosspost` workflow at :09 past the slot hours (covers EST and EDT), posting
  anything public on YouTube in the last 36 h that isn't on that platform yet. Up to 3
  attempts per platform per video; one platform failing never blocks the other. TikTok posts
  set `is_aigc: true` and start `SELF_ONLY` until the app audit passes. Captions carry the
  AI-assisted disclosure. Videos stay in the `buffer` release for 48 h after their YouTube
  slot so cross-posting has the file. Both platforms are off by default (config/crosspost.yaml).
  Not verifiable without accounts: TikTok refresh-token rotation (we alert if it rotates,
  since workflows can't update secrets) and the exact Graph API version. Check both on first use.

- **D35. Growth extras built** (config/growth.yaml, each switchable):
  (1) **Viewer-requested cases:** weekly, top comments on the last 14 days of videos → Haiku
  extracts case names → sanitized (plain text, ≤ 60 chars) → passed to discovery as quoted
  *data*, not instructions; requested cases still pass every gate, then get the "Requested
  Cases" playlist and a "You asked for this one" comment. (2) **Recurring segments** on the
  case card (STILL MISSING / SOLVED, DECADES LATER / STRANGE BUT TRUE). (3) **DNA-identification
  focus** on every 5th discovery.
- **D36. Growth extras not built:** multi-language dubs (YouTube's API can't add audio tracks,
  so it needs separate channels: owner decision), thumbnail A/B (Test & Compare isn't in the
  API), archivist storyline and Patreon/newsletter (wait for an audience).

## Open
- **Q1. Hands-off ceiling.** The YouTube API audit, TikTok audit, and OAuth app
  verification are one-time human steps. Until they pass, uploads are forced private.

## Known risks
- **Pro plan limits are the tightest tier and are shared with the owner's own Claude use.**
  Mitigated by the overnight window, adaptive caps and the buffer. If the owner often hits
  limits themselves, options are: Max plan, 2 shorts/day, or opting into the API backend.
- **Subscription use in automation:** Anthropic's terms for consumer plans can change.
  The owner should confirm current terms allow this before relying on it for the channel.
  Switching to the API backend is a one-line config change if needed.
- **YouTube "inauthentic / mass-produced content" policy** (formerly "repetitious content")
  is the biggest monetization risk for AI channels. Mitigated by real research, unique
  scripts, original visuals, and a consistent narrator persona.
- **YouTube API quota**: 10,000 units/day by default; one upload costs about 1,600, so 3
  shorts/day fits but leaves little headroom. Request an increase early.
- **True-crime sensitivity**: defamation and victim-family harm are hard gates (spec §5).
