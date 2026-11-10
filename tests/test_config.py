import pytest
import yaml

from pipeline.config import CONFIG_DIR, BudgetConfig, ModelsConfig, pipeline_enabled


def test_repo_config_loads(settings):
    assert settings.budget.global_weekly_usd < 25
    assert settings.schedule.timezone == "America/New_York"
    assert settings.models.tts.provider == "kokoro"
    assert settings.animation.paid_image_to_video["enabled"] is False


def test_writer_and_fact_judge_differ(settings):
    st = settings.models.stages
    assert st["script"].model != st["qa_fact"].model


def test_provider_caps_cannot_exceed_global():
    raw = yaml.safe_load((CONFIG_DIR / "budget.yaml").read_text())
    raw["providers"]["anthropic"] = 100
    with pytest.raises(ValueError, match="above global"):
        BudgetConfig(**raw)


def test_unpriced_model_rejected():
    raw = yaml.safe_load((CONFIG_DIR / "models.yaml").read_text())
    raw["stages"]["script"]["model"] = "claude-unknown"
    with pytest.raises(ValueError, match="no pricing"):
        ModelsConfig(**raw)


@pytest.mark.parametrize(
    ("val", "expected"), [("true", True), ("1", True), ("false", False), ("", False)]
)
def test_kill_switch(monkeypatch, val, expected):
    monkeypatch.setenv("PIPELINE_ENABLED", val)
    assert pipeline_enabled() is expected
