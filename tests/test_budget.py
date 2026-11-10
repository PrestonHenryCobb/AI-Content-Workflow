from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from pipeline.budget import (
    BudgetExceeded,
    Governor,
    QuotaExceeded,
    SubscriptionLimited,
    claude_cost,
    week_start,
)

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)        # Thu 10:00 ET (outside run window)
NIGHT = datetime(2026, 11, 12, 7, 0, tzinfo=UTC)       # Thu 02:00 ET (inside run window)


def gov(state, settings, now=NOW):
    return Governor(state, settings, now=now)


def test_week_starts_monday_eastern():
    ws = week_start(NOW, ZoneInfo("America/New_York"))
    assert ws == datetime(2026, 11, 9, 5, 0, tzinfo=UTC)  # Mon 00:00 EST


def test_claude_cost_and_batch_discount(settings):
    full = claude_cost(settings.models, "claude-sonnet-5-5", 1_000_000, 100_000)
    assert full == pytest.approx(3.0)
    assert claude_cost(settings.models, "claude-sonnet-5-5", 1_000_000, 100_000,
                       batch=True) == pytest.approx(1.5)


# ----- dollars -----
def test_images_within_cap(state, settings):
    g = gov(state, settings)
    g.authorize("images", 1.0)
    g.charge("images", "art", 1.0)
    assert g.status().spent_total == pytest.approx(1.0)


def test_provider_borrows_reserve_then_blocks(state, settings):
    g = gov(state, settings)
    caps = settings.budget.providers
    g.charge("images", "art", caps.images)
    g.authorize("images", caps.reserve - 0.01)
    g.charge("images", "art", caps.reserve)
    with pytest.raises(BudgetExceeded):
        g.authorize("images", 0.01)


def test_zero_cap_provider_only_borrows_reserve(state, settings):
    g = gov(state, settings)
    g.charge("images", "x", settings.budget.providers.images)
    g.charge("images", "x", settings.budget.providers.reserve)
    with pytest.raises(BudgetExceeded):
        g.authorize("video", 0.5)


def test_spend_from_last_week_ignored(state, settings):
    gov(state, settings, now=datetime(2026, 11, 5, 12, 0, tzinfo=UTC)).charge("images", "x", 3.0)
    assert gov(state, settings).status().spent_total == 0


def test_dollar_pace_triggers_degradation(state, settings):
    g = gov(state, settings)
    assert g.status().degradation_level == 0
    g.charge("images", "x", 3.0)
    g.charge("images", "x", 1.5)   # ~3.4 days in -> projects ~$9/week vs $5 cap
    st = g.status()
    assert st.active_degradations[0] == "disable_paid_video"


def test_unknown_provider_rejected(state, settings):
    with pytest.raises(ValueError):
        gov(state, settings).charge("openai", "x", 1.0)


# ----- YouTube quota -----
def test_youtube_quota(state, settings):
    g = gov(state, settings)
    insert = settings.budget.youtube_quota.cost_videos_insert
    for _ in range(6):
        g.use_youtube_quota("videos.insert", insert)
    with pytest.raises(QuotaExceeded):
        g.use_youtube_quota("videos.insert", insert)


# ----- Claude subscription -----
def test_llm_blocked_outside_window_unless_urgent(state, settings):
    g = gov(state, settings, now=NOW)
    with pytest.raises(SubscriptionLimited, match="window"):
        g.authorize_llm("script")
    g.authorize_llm("script", urgent=True)


def test_llm_allowed_in_window(state, settings):
    gov(state, settings, now=NIGHT).authorize_llm("script")


def test_llm_daily_cap(state, settings):
    g = gov(state, settings, now=NIGHT)
    for _ in range(settings.budget.subscription.max_calls_per_day):
        g.record_llm_call("claude-sonnet-5-5", "script", ok=True)
    with pytest.raises(SubscriptionLimited, match="daily cap"):
        g.authorize_llm("script")


def test_limit_hit_cooldown_and_adaptive_cap(state, settings):
    sub = settings.budget.subscription
    g = gov(state, settings, now=NIGHT)
    g.record_llm_call("claude-sonnet-5-5", "script", ok=False, limit_hit=True)
    st = g.subscription_status()
    assert st.cooldown_until == NIGHT + timedelta(hours=sub.cooldown_hours_after_limit)
    assert st.weekly_cap == int(sub.max_calls_per_week * sub.adapt_on_limit_factor)
    with pytest.raises(SubscriptionLimited, match="cooling down"):
        g.authorize_llm("script", urgent=True)
    later = gov(state, settings, now=NIGHT + timedelta(days=1))
    later.authorize_llm("script")   # cooldown over, next night's window


def test_adaptive_cap_has_floor(state, settings):
    sub = settings.budget.subscription
    g = gov(state, settings, now=NIGHT)
    for _ in range(30):
        g.record_llm_call("m", "s", ok=False, limit_hit=True)
    assert g.subscription_status().weekly_cap == sub.min_weekly_calls_floor


def test_subscription_pace_triggers_degradation(state, settings):
    g = gov(state, settings, now=NIGHT)
    for _ in range(150):   # ~3.1 days in -> projects ~340/week vs 220 cap
        g.record_llm_call("claude-sonnet-5-5", "script", ok=True)
    assert g.status().degradation_level > 0
