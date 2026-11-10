# AI-Content-Workflow

Autonomous faceless true-crime channel: cold cases and shocking real cases as 45–75 s
Shorts in a lo-fi PS2-era horror style, 2–3 per day, plus a weekly long-form compilation.
Publishes to YouTube (primary), TikTok and Instagram with no manual review.

**Start here:** [`docs/GOD_PROMPT.md`](docs/GOD_PROMPT.md) is the full spec. Every build
session starts from it.

## Status
- [x] Phase 0: spec ("god prompt")
- [x] Phase 1: skeleton, config, state DB, budget governor, CI
- [ ] Phase 2: brand package
- [ ] Phase 3: offline vertical slice (one case → finished video)
- [ ] Phase 4: YouTube publisher + buffer
- [ ] Phase 5: GitHub Actions automation, alerts, weekly digest
- [ ] Phase 6: weekly compilation
- [ ] Phase 7: analytics + learning loop
- [ ] Phase 8: TikTok / Instagram cross-posting
- [ ] Phase 9: growth extras

Decisions and open questions are logged in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Quick start (local)
```bash
uv sync
uv run pytest -q          # tests
uv run acw check-config   # validate config
uv run acw budget         # weekly spend vs. cap
uv run acw status         # kill switch, buffer, quota
```

## Layout
| Path | Purpose |
|---|---|
| `config/` | every tunable: budget, models, style, voice, animation, schedule, sources, strategy |
| `pipeline/` | stage code; `budget.py` governs all paid calls, `state.py` is the SQLite store |
| `render/` | PS2 post-process, Blender scene builder, parallax, fonts, SFX |
| `library/` | CC0 3D kits + reusable clip index |
| `brand/` | channel identity package |
| `prompts/` | versioned prompt templates |
| `docs/` | spec, decisions, setup checklist, runbook |

One-time human steps: [`docs/SETUP.md`](docs/SETUP.md). Operations: [`docs/RUNBOOK.md`](docs/RUNBOOK.md).
