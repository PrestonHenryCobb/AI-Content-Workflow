from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from pipeline.budget import (
    BudgetExceeded,
    Governor,
    QuotaExceeded,
    claude_cost,
    week_start,
)

# Thursday 2026-11-12 15:00 UTC (10:00 ET)
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)


def gov(state, settings, now=NOW):
    return Governor(state, settings, now=now)


def test_week_starts_monday_eastern():
    ws = week_start(NOW, ZoneInfo("America/New_York"))
    assert ws == datetime(2026, 11, 9, 5, 0, tzinfo=UTC)  # Mon 00:00 EST


def test_claude_cost_and_batch_discount(settings):
    full = claude_cost(settings.models, "claude-sonnet-5-5", 1_000_000, 100_000)
    assert full == pytest.approx(2.0 + 1.0)
    assert claude_cost(settings.models, "claude-sonnet-5-5", 1_000_000, 100_000,
                       batch=True) == pytest.approx(1.5)


def test_authorize_within_cap(state, settings):
    g = gov(state, settings)
    g.authorize("anthropic", 1.0)
    g.charge("anthropic", "script", 1.0)
    assert g.status().spent_total == pytest.approx(1.0)


def test_provider_borrows_reserve_then_blocks(state, settings):
    g = gov(state, settings)
    caps = settings.budget.providers
    g.charge("images", "art", caps.images)            # images cap used up
    g.authorize("images", caps.reserve - 0.01)         # reserve still available
    g.charge("images", "art", caps.reserve)            # reserve gone
    with pytest.raises(BudgetExceeded):
        g.authorize("images", 0.01)
    g.authorize("anthropic", 1.0)                      # other providers keep own cap


def test_zero_cap_provider_uses_only_reserve(state, settings):
    g = gov(state, settings)
    g.charge("anthropic", "x", settings.budget.providers.anthropic)
    g.charge("anthropic", "x", settings.budget.providers.reserve)
    with pytest.raises(BudgetExceeded):
        g.authorize("video", 0.5)


def test_spend_from_last_week_ignored(state, settings):
    last_week = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    gov(state, settings, now=last_week).charge("anthropic", "x", 10.0)
    assert gov(state, settings).status().spent_total == 0


def test_degradation_ladder_kicks_in(state, settings):
    g = gov(state, settings)
    assert g.status().degradation_level == 0
    # 3.4 days elapsed; spending $15 projects ~$31/week -> over 90% of $24
    g.charge("anthropic", "x", 9.0)
    g.charge("images", "x", 3.0)
    g.charge("anthropic", "x", 3.0)
    st = g.status()
    assert st.projected_total > settings.budget.global_weekly_usd
    assert st.active_degradations[0] == "disable_paid_video"
    assert g.is_degraded("disable_paid_video")


def test_youtube_quota(state, settings):
    g = gov(state, settings)
    insert = settings.budget.youtube_quota.cost_videos_insert
    for _ in range(6):
        g.use_youtube_quota("videos.insert", insert)
    with pytest.raises(QuotaExceeded):
        g.use_youtube_quota("videos.insert", insert)


def test_unknown_provider_rejected(state, settings):
    with pytest.raises(ValueError):
        gov(state, settings).charge("openai", "x", 1.0)
