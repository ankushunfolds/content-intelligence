"""Silent stand-in data must be detectable from outside the process.

The 2 Aug incident was not "the LLM broke" — it was "the LLM broke and the app
kept returning confident, well-formed, entirely template-generated briefs".
Mock providers throw nothing and log nothing, so absence of errors is not
evidence of a working product. These tests cover the config-level version of
the same trap: a deploy that comes up on defaults.
"""
from __future__ import annotations

import pytest

from app.config import Settings, settings

KEY = "test-monitor-key"


@pytest.fixture(autouse=True)
def _monitor_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_monitor_key", KEY, raising=False)


def _settings(**env) -> Settings:
    import os
    from unittest.mock import patch

    base = {
        "YOUTUBE_PROVIDER": "mock",
        "YOUTUBE_API_KEY": "",
        "LLM_PROVIDER": "mock",
        "GEMINI_API_KEY": "",
        "OPENAI_API_KEY": "",
    }
    base.update(env)
    with patch.dict(os.environ, base, clear=False):
        return Settings()


def test_default_config_is_reported_as_degraded():
    """The dangerous case: nothing is set, nothing errors, everything is fake."""
    modes = _settings().degraded_modes()

    assert len(modes) == 2
    assert any("YOUTUBE_PROVIDER" in m for m in modes)
    assert any("LLM_PROVIDER" in m for m in modes)


def test_fully_configured_is_clean():
    modes = _settings(
        YOUTUBE_PROVIDER="youtube",
        YOUTUBE_API_KEY="yt-key",
        LLM_PROVIDER="gemini",
        GEMINI_API_KEY="gm-key",
    ).degraded_modes()

    assert modes == []


def test_provider_set_but_key_missing_is_still_degraded():
    """The subtle one: LLM_PROVIDER=gemini looks configured, but with no key
    get_llm() silently returns MockLLM. Config that reads correct and behaves
    as mock is exactly how this stays invisible."""
    modes = _settings(LLM_PROVIDER="gemini", GEMINI_API_KEY="").degraded_modes()

    assert any("LLM_PROVIDER" in m for m in modes)


def test_youtube_key_without_provider_is_still_seed_data():
    modes = _settings(YOUTUBE_PROVIDER="mock", YOUTUBE_API_KEY="yt-key").degraded_modes()

    assert any("YOUTUBE_PROVIDER" in m for m in modes)


def test_health_summary_exposes_degraded_modes(client, monkeypatch):
    """A monitor polling from outside must be able to see this without shell
    access to read startup logs."""
    monkeypatch.setattr(settings, "youtube_provider", "mock", raising=False)
    monkeypatch.setattr(settings, "llm_provider", "mock", raising=False)

    response = client.get("/admin/health-summary?hours=1", headers={"X-Monitor-Key": KEY})

    assert response.status_code == 200
    assert response.json()["degraded_modes"], "an all-mock deploy must not report as clean"


def test_health_summary_is_clean_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "youtube_provider", "youtube", raising=False)
    monkeypatch.setattr(settings, "youtube_api_key", "yt-key", raising=False)
    monkeypatch.setattr(settings, "llm_provider", "gemini", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "gm-key", raising=False)

    response = client.get("/admin/health-summary?hours=1", headers={"X-Monitor-Key": KEY})

    assert response.json()["degraded_modes"] == []
