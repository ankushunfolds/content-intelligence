"""A model can return HTTP 200 and still hand back something unusable.

On 3 Aug 2026 a brief failed with `Expecting ',' delimiter: line 27 column 6`.
That escaped `_extract_json` as a bare `json.JSONDecodeError`, which carries no
`status_code`, so the event landed in the log with nothing to group on and the
monitoring endpoint's triage field stayed empty during a genuine fault.

These tests pin the classification of non-HTTP failures.
"""
from __future__ import annotations

import json

import pytest

from app.services.llm import LLMError, _extract_json


def test_valid_json_still_parses():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json_still_parses():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_embedded_in_prose_still_parses():
    assert _extract_json('Sure! Here you go:\n{"a": 1}\nHope that helps.') == {"a": 1}


def test_malformed_json_raises_a_classified_error():
    """The 3 Aug failure: a JSON-shaped body that doesn't actually parse."""
    truncated = '{"results": [{"id": 1, "topic": "AI"} {"id": 2'

    with pytest.raises(LLMError) as caught:
        _extract_json(truncated)

    assert caught.value.reason == "malformed_json"
    assert caught.value.status_code is None
    assert caught.value.failure_key == "malformed_json"


def test_malformed_json_is_not_a_bare_decode_error():
    """Regression guard: it must not escape as the raw exception again.

    A JSONDecodeError has no status_code and no reason, so it would be
    invisible to errors_by_status — the exact blind spot this closes.
    """
    with pytest.raises(LLMError):
        _extract_json('{"broken": ')

    # Still a ValueError subclass underneath, so existing handlers don't break.
    assert issubclass(LLMError, Exception)
    assert not issubclass(json.JSONDecodeError, LLMError)


def test_output_with_no_json_object_is_classified_separately():
    """Distinct from malformed: the model answered in prose and ignored the schema."""
    with pytest.raises(LLMError) as caught:
        _extract_json("I'm sorry, I can't help with that request.")

    assert caught.value.reason == "no_json_object"
    assert caught.value.failure_key == "no_json_object"


def test_http_failures_still_key_on_their_status():
    """`reason` must not displace the status code when there is one."""
    assert LLMError("retired", status_code=404).failure_key == "404"
    assert LLMError("quota", status_code=429).failure_key == "429"


def test_a_failure_with_neither_is_still_groupable():
    """Never return None as a dict key — it would collapse into a null bucket."""
    assert LLMError("something odd").failure_key == "unknown"
