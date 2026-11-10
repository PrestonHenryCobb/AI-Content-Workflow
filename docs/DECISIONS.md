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
  off by default. Estimated spend at 3 shorts/day plus 1 compilation: Claude ~$5–10, images
  ~$0.50–1, voice $0. The governor still drops to 2/day if spend is on track to pass the cap.
- **D7. Channel name: the pipeline generates ~20 candidates and checks handle availability;
  the owner picks from the shortlist.**
- **D8. Posting timezone: US Eastern.** Slots start at 08:00 / 14:00 / 20:00 ET and are
  tuned later by analytics.
- **D9. Voice: free local TTS (Kokoro) running inside GitHub Actions.** Word timestamps come
  from a local alignment pass (e.g. faster-whisper). The eerie tone comes from
  post-processing (pitch down slightly, EQ, reverb, tape hiss) to make up for the plainer
  base voice. ElevenLabs stays as an optional config switch if budget grows.
- **D10. Images: Flux Schnell (~$0.003/image)** via a pay-per-use API, at 6–8 stills per short.

## Open
- **Q1. Hands-off ceiling.** The YouTube API audit, TikTok audit, and OAuth app
  verification are one-time human steps. Until they pass, uploads are forced private.

## Known risks
- **YouTube "inauthentic / mass-produced content" policy** (formerly "repetitious content")
  is the biggest monetization risk for AI channels. Mitigated by real research, unique
  scripts, original visuals, and a consistent narrator persona.
- **YouTube API quota**: 10,000 units/day by default; one upload costs about 1,600, so 3
  shorts/day fits but leaves little headroom. Request an increase early.
- **True-crime sensitivity**: defamation and victim-family harm are hard gates (spec §5).
