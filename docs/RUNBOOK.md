# Runbook

## Kill switch
Set repo variable `PIPELINE_ENABLED=false`. Publishing stops at the next run; nothing else
is needed. Local check: `uv run acw status`.

## Commands
| Command | What it shows |
|---|---|
| `uv run acw check-config` | validates every `config/*.yaml` |
| `uv run acw budget` | this week's spend, remaining, daily allowance, active degradations |
| `uv run acw status` | kill switch, buffer depth, YouTube quota left today |

## Budget behavior
- Week runs Monday 00:00 → Sunday 23:59 US Eastern. Cap: `config/budget.yaml`.
- Each provider has its own cap and may borrow from `reserve`; the global cap is never exceeded.
- When projected weekly spend passes 90% of the cap, the degradation ladder turns on one rung
  per 5% overshoot (paid video off → fewer Blender shots → library clips only → batch API →
  fewer stills → 2 shorts/day → compilation reuses narration).
- YouTube quota resets at midnight Pacific; tracked separately.

## Alerts (Phase 5)
| Alert | Meaning | Self-heal |
|---|---|---|
| slot missed | a scheduled short failed | buffer video published instead |
| buffer low | fewer than 2 spare videos | refill runs on next low-cost day |
| budget 75% / 90% | spend pace high | degradation ladder engages |
| token expiring | OAuth refresh failing | needs owner: re-run auth script |
| policy notice | strike/claim on a video | publishing pauses; owner digest flags it |
