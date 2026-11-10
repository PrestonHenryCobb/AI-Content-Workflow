# Runbook

## Kill switch
Set repo variable `PIPELINE_ENABLED=false`. Publishing stops at the next run; nothing else
is needed. Local check: `uv run acw status`.

## Commands
| Command | What it shows |
|---|---|
| `uv run acw check-config` | validates every `config/*.yaml` |
| `uv run acw budget` | this week's spend, Claude calls today/week vs. caps, cooldown, degradations |
| `uv run acw status` | kill switch, buffer depth, YouTube quota left today |
| `uv run acw make-short --job-id X [--case "hint"] [--urgent]` | produce one short (no upload); resumes if re-run |
| `uv run acw make-short --job-id X --offline` | fictional test short, no network (CI does this on every push) |

## Making a test short in GitHub
Actions → **slice** → Run workflow (optionally type a case or theme). When it finishes,
download the `slice-<run id>` artifact: `data/jobs/slice-*/short.mp4` plus every
intermediate file (case.json, fact_pack.json, script.json, qa.json, narration.wav, stills/).

## Claude subscription (Pro) behavior
- All Claude calls run through `claude -p` on your Pro plan; no API bill.
- Generation runs only 01:00–06:00 ET so your daytime Claude use is untouched.
- Caps: 40 calls per nightly run, 45/day, 220/week (`config/budget.yaml → subscription`).
- If the plan limit is hit: 5 h cooldown, this week's cap drops 10%, spare videos fill slots.
- If *you* keep hitting limits in your own use: lower `shorts_per_day` to 2 in
  `config/schedule.yaml`, or upgrade the plan and set `subscription.plan` to match.

## Dollar budget behavior
- Week runs Monday 00:00 → Sunday 23:59 US Eastern. Cap: `config/budget.yaml` ($5: images + reserve).
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
| budget 75% / 90% | spend or Claude-usage pace high | degradation ladder engages |
| plan limit hit | Pro usage limit reached | cooldown 5 h, cap shrinks, buffer covers |
| token expiring | YouTube OAuth or Claude token failing | needs owner: re-run `claude setup-token` or the YouTube auth script |
| policy notice | strike/claim on a video | publishing pauses; owner digest flags it |
