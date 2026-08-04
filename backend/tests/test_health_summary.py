"""The monitoring endpoint has to be right when things are worst.

Two failures this endpoint had on 3 Aug 2026:
  - error_count was len() of a 50-row page, so a 200-error incident read as 50
  - every provider failure was one undifferentiated `llm.failure`, so a retired
    model (404), an exhausted quota (429) and a capacity blip (503) — needing a
    deploy, a billing change, and nothing respectively — looked identical
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.models import EventLog
from app.utils.logging import record_event
from app.utils.time import utcnow

KEY = "test-monitor-key"


@pytest.fixture(autouse=True)
def _monitor_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_monitor_key", KEY, raising=False)


def _summary(client, hours: int = 24) -> dict:
    response = client.get(f"/admin/health-summary?hours={hours}", headers={"X-Monitor-Key": KEY})
    assert response.status_code == 200, response.text
    return response.json()


def test_error_count_is_not_capped_at_the_page_size(client, db):
    """The bug: 60 errors used to report as 50, because the count came from a
    LIMIT 50 fetch. Under-reporting scales with severity, which is backwards."""
    for i in range(60):
        db.add(EventLog(kind="llm.failure", level="error", message=f"e{i}", created_at=utcnow()))
    db.commit()

    data = _summary(client)

    assert data["error_count"] == 60
    assert data["errors_by_kind"]["llm.failure"] == 60
    assert len(data["recent_errors"]) == 10, "recent list stays a preview, not the count"


def test_status_codes_are_broken_out(client, db):
    record_event(db, "llm.failure", "retired model", level="error", status_code=404)
    record_event(db, "llm.failure", "quota", level="error", status_code=429)
    record_event(db, "llm.failure", "capacity", level="error", status_code=503)
    record_event(db, "llm.failure", "capacity again", level="error", status_code=503)

    data = _summary(client)

    assert data["errors_by_kind"]["llm.failure"] == 4
    assert data["errors_by_status"] == {"404": 1, "429": 1, "503": 2}


def test_recent_errors_expose_meta(client, db):
    """Whose brief degraded, and at what stage — both were unanswerable before."""
    record_event(
        db, "llm.failure", "brief fell back", level="error", status_code=503, stage="brief", user_id=7
    )

    meta = _summary(client)["recent_errors"][0]["meta"]

    assert meta["status_code"] == 503
    assert meta["stage"] == "brief"
    assert meta["user_id"] == 7


def test_events_without_a_status_code_are_not_counted(client, db):
    """onboarding.partial has no HTTP status; it must not become a "None" bucket."""
    record_event(db, "onboarding.partial", "bad url", level="error")

    data = _summary(client)

    assert data["error_count"] == 1
    assert data["errors_by_status"] == {}


def test_non_http_llm_failures_still_appear_in_the_triage_field(client, db):
    """A 200 response with an unparseable body is a real fault with no status.

    Seen in production 3 Aug 17:17. Keying this dict only on status_code left
    it empty during that fault, so the monitor's primary triage field read
    "nothing structural" while looking directly at a structural problem.
    """
    record_event(
        db,
        "llm.failure",
        "brief narration fell back to mock: Model returned malformed JSON",
        level="error",
        status_code=None,
        failure_reason="malformed_json",
        stage="brief",
    )

    data = _summary(client)

    assert data["error_count"] == 1
    assert data["errors_by_status"] == {"malformed_json": 1}


def test_http_and_non_http_failures_group_side_by_side(client, db):
    """One field to read, whether or not the failure had a status code."""
    record_event(db, "llm.failure", "retired", level="error", status_code=404)
    record_event(db, "llm.failure", "bad body", level="error", failure_reason="malformed_json")
    record_event(db, "llm.failure", "no object", level="error", failure_reason="no_json_object")

    assert _summary(client)["errors_by_status"] == {
        "404": 1,
        "malformed_json": 1,
        "no_json_object": 1,
    }


def test_window_is_respected(client, db):
    from datetime import timedelta

    db.add(EventLog(kind="llm.failure", level="error", message="old", created_at=utcnow() - timedelta(hours=48)))
    db.add(EventLog(kind="llm.failure", level="error", message="new", created_at=utcnow()))
    db.commit()

    assert _summary(client, hours=24)["error_count"] == 1
    assert _summary(client, hours=72)["error_count"] == 2


def test_info_events_are_not_errors(client, db):
    record_event(db, "classification.run", "classified 20 videos")

    assert _summary(client)["error_count"] == 0
