"""Weekly budget governor (GOD_PROMPT §4).

Two things are governed:

1. **Dollars** (images, optional API). Every paid call goes through `authorize()` before
   and `charge()` after. Caps are per provider; a provider past its cap may borrow from
   the shared `reserve`. The global cap is never exceeded.
2. **Claude subscription usage** (DECISIONS D14). Every `claude -p` call goes through
   `authorize_llm()` before and `record_llm_call()` after. Calls only run inside the
   overnight window, under daily/weekly caps, and pause for a cooldown after the plan's
   limit is hit. Each limit hit shrinks this week's cap so the pacing learns the real limit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pipeline.config import BudgetConfig, ModelsConfig, Settings, load_settings
from pipeline.state import State

PROVIDERS = ("anthropic", "images", "tts", "video")
YOUTUBE_RESET_TZ = ZoneInfo("America/Los_Angeles")  # YouTube quota resets midnight Pacific


class BudgetExceeded(RuntimeError):
    pass


class QuotaExceeded(RuntimeError):
    pass


class SubscriptionLimited(RuntimeError):
    """Claude subscription call refused: outside window, over cap, or cooling down."""


@dataclass(frozen=True)
class SubscriptionStatus:
    calls_today: int
    calls_week: int
    daily_cap: int
    weekly_cap: int               # effective cap after adapting to limit hits
    limit_hits_week: int
    cooldown_until: datetime | None
    in_run_window: bool
    projected_week: float


@dataclass(frozen=True)
class BudgetStatus:
    week_start: datetime
    spent_total: float
    spent_by_provider: dict[str, float]
    global_cap: float
    projected_total: float
    subscription: SubscriptionStatus
    degradation_level: int
    active_degradations: list[str]

    @property
    def remaining(self) -> float:
        return max(0.0, self.global_cap - self.spent_total)

    @property
    def daily_allowance(self) -> float:
        """Even pacing: remaining budget divided over remaining days (incl. today)."""
        days_left = max(1, 7 - (datetime.now(UTC) - self.week_start).days)
        return self.remaining / days_left


def week_start(now: datetime, tz: ZoneInfo) -> datetime:
    """Most recent Monday 00:00 in `tz`, returned in UTC."""
    local = now.astimezone(tz)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday.astimezone(UTC)


def claude_cost(
    models: ModelsConfig, model: str, input_tokens: int, output_tokens: int,
    cache_read_tokens: int = 0, batch: bool = False,
) -> float:
    p = models.pricing[model]
    usd = (input_tokens * p.input + output_tokens * p.output
           + cache_read_tokens * p.cache_read) / 1_000_000
    return usd * (models.batch_discount if batch else 1.0)


class Governor:
    def __init__(self, state: State, settings: Settings | None = None,
                 now: datetime | None = None) -> None:
        self.state = state
        self.settings = settings or load_settings()
        self._now = now

    @property
    def cfg(self) -> BudgetConfig:
        return self.settings.budget

    def now(self) -> datetime:
        return self._now or datetime.now(UTC)

    def _week_start(self) -> datetime:
        return week_start(self.now(), ZoneInfo(self.settings.schedule.timezone))

    # ----- reads -----
    def status(self) -> BudgetStatus:
        ws = self._week_start()
        by_provider = self.state.spend_by_provider_since(ws.isoformat(timespec="seconds"))
        total = sum(by_provider.values())
        projected = total / self._elapsed_days(ws) * 7
        sub = self.subscription_status()
        level = max(
            self._degradation_level(projected / self.cfg.global_weekly_usd),
            self._degradation_level(sub.projected_week / sub.weekly_cap),
        )
        return BudgetStatus(
            week_start=ws,
            spent_total=total,
            spent_by_provider=by_provider,
            global_cap=self.cfg.global_weekly_usd,
            projected_total=projected,
            subscription=sub,
            degradation_level=level,
            active_degradations=self.cfg.degradation_ladder[:level],
        )

    def _elapsed_days(self, ws: datetime) -> float:
        return max(1.0, (self.now() - ws).total_seconds() / 86400)  # floor avoids spikes

    def _degradation_level(self, ratio: float) -> int:
        """`ratio` = projected weekly usage / weekly cap."""
        if ratio <= self.cfg.degrade_at_fraction:
            return 0
        # one rung per 5% of projected overshoot past the threshold
        steps = math.ceil((ratio - self.cfg.degrade_at_fraction) / 0.05)
        return min(steps, len(self.cfg.degradation_ladder))

    def is_degraded(self, rung: str) -> bool:
        return rung in self.status().active_degradations

    def _provider_cap(self, provider: str) -> float:
        caps = self.cfg.providers
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}")
        return float(getattr(caps, provider))

    def headroom(self, provider: str) -> float:
        """USD this provider may still spend this week (own cap + unused shared reserve)."""
        st = self.status()
        spent = st.spent_by_provider
        overflow = sum(max(0.0, spent.get(p, 0.0) - self._provider_cap(p)) for p in PROVIDERS)
        reserve_left = max(0.0, self.cfg.providers.reserve - overflow)
        own_left = max(0.0, self._provider_cap(provider) - spent.get(provider, 0.0))
        return min(own_left + reserve_left, st.remaining)

    # ----- writes -----
    def authorize(self, provider: str, estimated_usd: float) -> None:
        """Raise BudgetExceeded if the estimated call would breach a cap."""
        if estimated_usd <= 0:
            return
        room = self.headroom(provider)
        if estimated_usd > room + 1e-9:
            raise BudgetExceeded(
                f"{provider}: need ${estimated_usd:.4f}, only ${room:.4f} left this week"
            )

    def charge(self, provider: str, stage: str, usd: float, job_id: str | None = None,
               meta: dict[str, Any] | None = None) -> None:
        self._provider_cap(provider)  # validates name
        self.state.record_spend(provider, stage, usd, job_id, meta,
                                ts=self.now().isoformat(timespec="seconds"))

    # ----- YouTube quota -----
    def _quota_day(self) -> str:
        return self.now().astimezone(YOUTUBE_RESET_TZ).date().isoformat()

    def youtube_quota_left(self) -> int:
        used = self.state.quota_used("youtube", self._quota_day())
        return self.cfg.youtube_quota.daily_units - used

    def use_youtube_quota(self, op: str, units: int) -> None:
        if units > self.youtube_quota_left():
            raise QuotaExceeded(f"youtube {op}: {units} units > {self.youtube_quota_left()} left")
        self.state.record_quota("youtube", self._quota_day(), op, units)

    # ----- Claude subscription usage -----
    def _tz(self) -> ZoneInfo:
        return ZoneInfo(self.settings.schedule.timezone)

    def _in_run_window(self) -> bool:
        w = self.cfg.subscription.run_window
        local = self.now().astimezone(self._tz()).strftime("%H:%M")
        if w.start <= w.end:
            return w.start <= local < w.end
        return local >= w.start or local < w.end  # window wraps midnight

    def subscription_status(self) -> SubscriptionStatus:
        sub = self.cfg.subscription
        ws = self._week_start()
        local_midnight = self.now().astimezone(self._tz()).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).astimezone(UTC)
        calls_week = self.state.llm_calls_since(ws.isoformat(timespec="seconds"))
        calls_today = self.state.llm_calls_since(local_midnight.isoformat(timespec="seconds"))
        hits = self.state.limit_hits_since(ws.isoformat(timespec="seconds"))
        weekly_cap = max(
            sub.min_weekly_calls_floor,
            int(sub.max_calls_per_week * sub.adapt_on_limit_factor ** len(hits)),
        )
        cooldown_until = None
        if hits:
            until = datetime.fromisoformat(hits[-1]) + timedelta(
                hours=sub.cooldown_hours_after_limit
            )
            if until > self.now():
                cooldown_until = until
        return SubscriptionStatus(
            calls_today=calls_today,
            calls_week=calls_week,
            daily_cap=sub.max_calls_per_day,
            weekly_cap=weekly_cap,
            limit_hits_week=len(hits),
            cooldown_until=cooldown_until,
            in_run_window=self._in_run_window(),
            projected_week=calls_week / self._elapsed_days(ws) * 7,
        )

    def authorize_llm(self, stage: str, urgent: bool = False) -> None:
        """Raise SubscriptionLimited unless a subscription call may run now.

        `urgent=True` (healthcheck refilling an empty slot) may run outside the overnight
        window, but never during a cooldown or over the caps.
        """
        if self.settings.models.backend != "claude_code":
            return
        st = self.subscription_status()
        if st.cooldown_until is not None:
            raise SubscriptionLimited(
                f"{stage}: plan limit hit, cooling down until {st.cooldown_until.isoformat()}"
            )
        if not urgent and not st.in_run_window:
            raise SubscriptionLimited(f"{stage}: outside overnight run window")
        if st.calls_today >= st.daily_cap:
            raise SubscriptionLimited(f"{stage}: daily cap {st.daily_cap} reached")
        if st.calls_week >= st.weekly_cap:
            raise SubscriptionLimited(f"{stage}: weekly cap {st.weekly_cap} reached")

    def record_llm_call(
        self, model: str, stage: str, ok: bool, limit_hit: bool = False,
        job_id: str | None = None, duration_s: float | None = None,
        input_tokens: int | None = None, output_tokens: int | None = None,
    ) -> None:
        self.state.record_llm_call(
            self.settings.models.backend, model, stage, ok, limit_hit, job_id, duration_s,
            input_tokens, output_tokens, ts=self.now().isoformat(timespec="seconds"),
        )
