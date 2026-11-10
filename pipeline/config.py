"""Typed loaders for config/*.yaml. Invalid config fails fast at startup."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("ACW_CONFIG_DIR", REPO_ROOT / "config"))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- budget.yaml ----------
class ProviderCaps(_Strict):
    anthropic: float = Field(ge=0)
    images: float = Field(ge=0)
    tts: float = Field(ge=0)
    video: float = Field(ge=0)
    reserve: float = Field(ge=0)


class YouTubeQuota(_Strict):
    daily_units: int = Field(gt=0)
    cost_videos_insert: int
    cost_thumbnails_set: int
    cost_playlist_insert: int
    cost_comment_insert: int


class BudgetConfig(_Strict):
    week_starts_on: Literal["monday"]
    global_weekly_usd: float = Field(gt=0)
    warn_at_fraction: float = Field(gt=0, le=1)
    degrade_at_fraction: float = Field(gt=0, le=1)
    providers: ProviderCaps
    degradation_ladder: list[str]
    youtube_quota: YouTubeQuota

    @model_validator(mode="after")
    def _caps_fit_global(self) -> BudgetConfig:
        p = self.providers
        total = p.anthropic + p.images + p.tts + p.video + p.reserve
        if total > self.global_weekly_usd + 1e-9:
            raise ValueError(
                f"provider caps sum to ${total:.2f}, above global ${self.global_weekly_usd:.2f}"
            )
        return self


# ---------- models.yaml ----------
class Price(_Strict):
    input: float
    output: float
    cache_read: float


class StageModel(_Strict):
    model: str
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    batch: bool = False


class ImageConfig(_Strict):
    provider: Literal["fal", "replicate"]
    model: str
    usd_per_image: float
    stills_per_short: int


class TTSConfig(_Strict):
    provider: Literal["kokoro", "elevenlabs"]


class ModelsConfig(_Strict):
    pricing: dict[str, Price]
    batch_discount: float = Field(gt=0, le=1)
    stages: dict[str, StageModel]
    images: ImageConfig
    tts: TTSConfig

    @model_validator(mode="after")
    def _priced(self) -> ModelsConfig:
        missing = {s.model for s in self.stages.values()} - set(self.pricing)
        if missing:
            raise ValueError(f"no pricing for models: {sorted(missing)}")
        return self


# ---------- schedule.yaml ----------
class Compilation(_Strict):
    day: Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    time: str


class BufferCfg(_Strict):
    target: int = Field(ge=0)
    minimum_before_alert: int = Field(ge=0)


class ScheduleConfig(_Strict):
    timezone: str
    shorts_per_day: int = Field(ge=1, le=6)
    slots: list[str]
    compilation: Compilation
    buffer: BufferCfg
    lead_time_hours: int = Field(ge=0)

    @model_validator(mode="after")
    def _slots_match(self) -> ScheduleConfig:
        if len(self.slots) < self.shorts_per_day:
            raise ValueError("fewer slots than shorts_per_day")
        return self


# ---------- animation.yaml ----------
class AnimationConfig(BaseModel):
    parallax: dict[str, Any]
    blender: dict[str, Any]
    fx: dict[str, Any]
    clip_library: dict[str, Any]
    paid_image_to_video: dict[str, Any]


def _load(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


class Settings(BaseModel):
    budget: BudgetConfig
    models: ModelsConfig
    schedule: ScheduleConfig
    animation: AnimationConfig
    style: dict[str, Any]
    voice: dict[str, Any]
    sources: dict[str, Any]
    strategy: dict[str, Any]


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    return Settings(
        budget=BudgetConfig(**_load("budget.yaml")),
        models=ModelsConfig(**_load("models.yaml")),
        schedule=ScheduleConfig(**_load("schedule.yaml")),
        animation=AnimationConfig(**_load("animation.yaml")),
        style=_load("style.yaml"),
        voice=_load("voice.yaml"),
        sources=_load("sources.yaml"),
        strategy=_load("strategy.yaml"),
    )


def pipeline_enabled() -> bool:
    """Global kill switch. Anything that publishes must check this."""
    return os.environ.get("PIPELINE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
