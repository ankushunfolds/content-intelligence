"""Transient provider failures must be retried, permanent ones must not.

Context: on 3 Aug 2026 a single 503 ("spikes in demand are usually temporary")
dropped a user's daily brief to template text for the rest of the day, because
briefs are cached one-per-user-per-day and the fallback fired on first error.
"""
from __future__ import annotations

import httpx
import pytest

from app.services import llm as llm_module
from app.services.llm import GeminiLLM, LLMError


def _response(status: int, *, text: str = "", headers: dict | None = None) -> httpx.Response:
    body = text or '{"candidates":[{"content":{"parts":[{"text":"{\\"ok\\":true}"}]}}]}'
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        content=body.encode(),
        request=httpx.Request("POST", "https://example.invalid"),
    )


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    """Assert on retry *behaviour*, not on wall-clock patience."""
    monkeypatch.setattr(llm_module.time, "sleep", lambda _: None)


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    monkeypatch.setattr(llm_module.settings, "llm_max_retries", 2, raising=False)
    monkeypatch.setattr(llm_module.settings, "llm_retry_base_delay", 0.01, raising=False)
    monkeypatch.setattr(llm_module.settings, "llm_classify_model", "gemini-3.5-flash", raising=False)


def _patch_post(monkeypatch, responses: list):
    """Serve `responses` in order; record how many calls were made."""
    calls = {"n": 0}

    def fake_post(*args, **kwargs):
        item = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    return calls


def test_503_is_retried_and_can_succeed(monkeypatch):
    """The exact failure seen in production: transient, then fine."""
    calls = _patch_post(monkeypatch, [_response(503), _response(200)])

    result = GeminiLLM("k").complete_json("sys", "user")

    assert result == {"ok": True}
    assert calls["n"] == 2, "should have retried the 503 rather than giving up"


def test_429_is_retried(monkeypatch):
    calls = _patch_post(monkeypatch, [_response(429), _response(429), _response(200)])

    assert GeminiLLM("k").complete_json("sys", "user") == {"ok": True}
    assert calls["n"] == 3


def test_retries_are_bounded(monkeypatch):
    """A sustained outage must fail fast to the caller's mock fallback."""
    calls = _patch_post(monkeypatch, [_response(503)])

    with pytest.raises(LLMError):
        GeminiLLM("k").complete_json("sys", "user")

    assert calls["n"] == 3, "max_retries=2 means three attempts total, not unlimited"


def test_404_is_not_retried(monkeypatch):
    """A retired model returns 404 on every attempt — retrying just burns quota."""
    calls = _patch_post(monkeypatch, [_response(404, text='{"error":{"code":404}}')])

    with pytest.raises(LLMError):
        GeminiLLM("k").complete_json("sys", "user")

    assert calls["n"] == 1


def test_400_is_not_retried(monkeypatch):
    calls = _patch_post(monkeypatch, [_response(400, text='{"error":{"code":400}}')])

    with pytest.raises(LLMError):
        GeminiLLM("k").complete_json("sys", "user")

    assert calls["n"] == 1


def test_network_error_is_retried(monkeypatch):
    """A connection reset has the same character as a 503."""
    calls = _patch_post(monkeypatch, [httpx.ConnectError("reset"), _response(200)])

    assert GeminiLLM("k").complete_json("sys", "user") == {"ok": True}
    assert calls["n"] == 2


def test_network_error_propagates_after_exhausting_retries(monkeypatch):
    calls = _patch_post(monkeypatch, [httpx.ConnectError("reset")])

    with pytest.raises(httpx.HTTPError):
        GeminiLLM("k").complete_json("sys", "user")

    assert calls["n"] == 3


def test_retry_after_header_is_honoured(monkeypatch):
    """If the provider says how long to wait, use that instead of our guess."""
    slept: list[float] = []
    monkeypatch.setattr(llm_module.time, "sleep", slept.append)
    _patch_post(
        monkeypatch,
        [_response(429, headers={"Retry-After": "7"}), _response(200)],
    )

    GeminiLLM("k").complete_json("sys", "user")

    assert slept and slept[0] == pytest.approx(7.0)


def test_thinking_config_400_retries_without_the_field(monkeypatch):
    """gemini-3.5-flash-lite rejects thinkingConfig outright. A cost knob must
    never be the reason a request fails."""
    sent: list[dict] = []

    def fake_post(*args, **kwargs):
        sent.append(kwargs["json"]["generationConfig"])
        return _response(400) if len(sent) == 1 else _response(200)

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)

    assert GeminiLLM("k").complete_json("sys", "user", thinking_budget=0) == {"ok": True}
    assert "thinkingConfig" in sent[0]
    assert "thinkingConfig" not in sent[1], "retry should drop the offending field"
