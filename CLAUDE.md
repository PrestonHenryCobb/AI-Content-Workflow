# CLAUDE.md — rules for sessions maintaining this repo

- `docs/GOD_PROMPT.md` is the spec. `docs/DECISIONS.md` records every override and owner
  answer; read both before changing behavior. Add a `D<n>` entry for any non-obvious choice.
- Python 3.12, `uv`. Before every commit: `uv run ruff check . && uv run mypy && uv run pytest -q`.
- Every Claude call goes through `pipeline.llm.LLM.complete()`, which runs `claude -p` on the
  owner's Pro subscription and is paced by `Governor.authorize_llm()`. Never call the
  Anthropic API directly and never add `ANTHROPIC_API_KEY` to workflows (DECISIONS D14).
- Every paid (dollar) call goes through `pipeline.budget.Governor` (`authorize` then `charge`).
  Every YouTube API call goes through `Governor.use_youtube_quota`. No exceptions.
- Anything that publishes must check `pipeline.config.pipeline_enabled()` and default to dry-run.
- Tests never hit paid or external APIs; mock providers.
- Never commit media, `.env`, or `data/state.db` to the code branch. State goes to the `state`
  branch and spare videos to the `buffer` release via `scripts/state.sh` (DECISIONS D27).
- Model IDs and prices live only in `config/models.yaml`. Don't hardcode them elsewhere.
- Keep `README.md` status, `docs/SETUP.md` and `docs/RUNBOOK.md` current with each change.
- Hard content rules (GOD_PROMPT §5) are gates, not guidelines: no naming uncharged people,
  no realistic faces of real people, no graphic detail, skip cases with active trials.
