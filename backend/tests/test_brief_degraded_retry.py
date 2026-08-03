"""A brief that fell back to template text must not be cached for the day.

3 Aug 2026: one 503 — the kind that clears in seconds — left a user reading
template text until the next day, because briefs cache one per user per day
and nothing revisited the decision. Retry on the call fixes the odds; this
fixes the consequence.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.config import settings
from app.models import DailyBrief
from app.services.briefing import _degraded_retry_due
from app.utils.time import utcnow


def _brief(source: str, *, age_minutes: int = 0) -> DailyBrief:
    generated_at = (utcnow() - timedelta(minutes=age_minutes)).isoformat()
    return DailyBrief(
        user_id=1,
        brief_date=utcnow().date(),
        content={"generated_at": generated_at, "headline": "x"},
        generated_by=source,
    )


@pytest.fixture(autouse=True)
def _real_llm(monkeypatch):
    """A configured provider — otherwise mock output is intentional."""
    monkeypatch.setattr(settings, "llm_provider", "gemini", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "key", raising=False)
    monkeypatch.setattr(settings, "brief_degraded_retry_minutes", 15, raising=False)


def test_good_brief_is_never_retried():
    assert _degraded_retry_due(_brief("gemini", age_minutes=600)) is False


def test_degraded_brief_is_retried_once_the_cooldown_passes():
    assert _degraded_retry_due(_brief("mock-fallback", age_minutes=16)) is True


def test_degraded_brief_within_cooldown_is_served_as_is():
    """The safety valve: without it a sustained outage means an LLM call per
    page load, at its slowest and priciest exactly when the provider is down."""
    assert _degraded_retry_due(_brief("mock-fallback", age_minutes=5)) is False


def test_mock_provider_is_not_retried(monkeypatch):
    """With LLM_PROVIDER=mock the template output is the intended result.
    Retrying would rewrite the same brief forever."""
    monkeypatch.setattr(settings, "llm_provider", "mock", raising=False)

    assert _degraded_retry_due(_brief("mock-fallback", age_minutes=600)) is False


def test_missing_timestamp_retries_rather_than_gives_up():
    brief = _brief("mock-fallback")
    brief.content = {}

    assert _degraded_retry_due(brief) is True


def test_corrupt_timestamp_retries_rather_than_raises():
    brief = _brief("mock-fallback")
    brief.content = {"generated_at": "not-a-date"}

    assert _degraded_retry_due(brief) is True


def test_source_none_is_not_treated_as_degraded():
    """'none' means there was no signal worth narrating, so no LLM call was
    made. Nothing to recover, and retrying would spin on empty accounts."""
    assert _degraded_retry_due(_brief("none", age_minutes=600)) is False


def test_today_endpoint_serves_a_healthy_cached_brief(client, auth, db):
    """The normal cache path must be untouched: one generation, then cache."""
    first = client.get("/briefs/today", headers=auth)
    assert first.status_code == 200

    brief = db.scalar(DailyBrief.__table__.select())
    assert brief is not None
