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

## Open — owner input needed
- **Q1. Weekly budget.** What's the $ ceiling per week? Rough estimate for 21 shorts + 1
  compilation: ~$25–60/wk on stills only, ~$80–200/wk with image-to-video hero shots.
- **Q2. Channel name.** Pipeline will propose ~20 candidates; owner picks or lets it auto-pick.
- **Q3. Timezone** for posting slots (defaults to US Eastern).
- **Q4. Hands-off ceiling.** The YouTube API audit, TikTok audit, and OAuth app
  verification are one-time human steps. Until they pass, uploads are forced private.

## Known risks
- **YouTube "inauthentic / mass-produced content" policy** (formerly "repetitious content")
  is the biggest monetization risk for AI channels. Mitigated by real research, unique
  scripts, original visuals, and a consistent narrator persona.
- **YouTube API quota**: 10,000 units/day by default; one upload costs about 1,600, so 3
  shorts/day fits but leaves little headroom. Request an increase early.
- **True-crime sensitivity**: defamation and victim-family harm are hard gates (spec §5).
