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
