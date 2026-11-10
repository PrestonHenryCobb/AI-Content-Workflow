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

## Open
- **Q1. Hands-off ceiling.** The YouTube API audit, TikTok audit, and OAuth app
  verification are one-time human steps. Until they pass, uploads are forced private.

## Known risks
- **Governor state lives in `data/state.db`, which is ephemeral on Actions runners.** Until
  Phase 5 persists it (bucket or a state branch), caps only apply within a single run.
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
