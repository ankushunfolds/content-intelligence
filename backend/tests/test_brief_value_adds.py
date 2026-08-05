"""Tier-1 additions: projection onto the user's own channel, confidence,
quiet days, and the rules governing when a brief is emailed.

The email gating carries the most risk here — every wrong decision is either
a missing email or an unwanted one landing in a real inbox.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.models import DailyBrief, User
from app.services.briefing import _fallback_headline, confidence_for
from app.utils.security import create_unsubscribe_token, decode_token, decode_unsubscribe_token
from app.utils.time import utcnow
from app.workers.jobs import _email_brief


# --- Confidence ----------------------------------------------------------


def test_confidence_falls_as_the_sample_thins():
    assert confidence_for(40, 8)["level"] == "solid"
    assert confidence_for(8, 3)["level"] == "moderate"
    assert confidence_for(3, 1)["level"] == "thin"


def test_a_wide_sample_from_one_creator_is_not_solid():
    """40 videos from a single channel is one creator's hobby horse, not a trend."""
    assert confidence_for(40, 1)["level"] != "solid"


def test_thin_confidence_says_so_in_words():
    note = confidence_for(2, 1)["note"]
    assert "2 videos" in note
    assert "1 creator" in note and "creators" not in note, "should not pluralise a single creator"


# --- Quiet days ----------------------------------------------------------


def test_quiet_day_and_empty_account_are_different_messages():
    """Telling someone with no channels that their niche is quiet is nonsense."""
    quiet = _fallback_headline([], [], [], has_channels=True)
    unset = _fallback_headline([], [], [], has_channels=False)

    assert "quiet" in quiet.lower()
    assert "add a few competitors" in unset.lower()
    assert quiet != unset


def test_quiet_day_flag_is_false_without_channels(client, auth):
    """No channels means unfinished setup, which must not read as a calm niche."""
    body = client.get("/intelligence/today", headers=auth).json()
    assert body["quiet_day"] is False


# --- Projection ----------------------------------------------------------


def test_projection_is_arithmetic_on_the_user_s_own_median(client, auth, db):
    """Expected views = their median x the topic's average performance."""
    client.post(
        "/channels/onboarding",
        headers=auth,
        json={"own_channel": "@me", "competitors": ["@rival1", "@rival2"], "niche": "AI"},
    )
    client.post("/intelligence/refresh", headers=auth)

    body = client.get("/intelligence/today", headers=auth).json()
    opportunities = body["opportunities"]
    if not opportunities:
        pytest.skip("seed data produced no opportunities in this window")

    projection = opportunities[0]["projection"]
    assert projection["your_baseline"] > 0, "own channel median should be known"
    assert projection["expected_views"] > 0
    assert projection["expected_views_display"]


# --- Unsubscribe tokens --------------------------------------------------


def test_unsubscribe_token_cannot_authenticate():
    """It reaches an inbox, so it must only ever be able to turn email off."""
    token = create_unsubscribe_token(5)
    assert decode_unsubscribe_token(token) == 5
    assert decode_token(token) is None


def test_unsubscribe_endpoint_rejects_junk(client):
    assert client.post("/briefs/unsubscribe", json={"token": "nonsense"}).status_code == 400


def test_unsubscribe_endpoint_turns_email_off(client, db):
    signup = client.post(
        "/auth/signup", json={"email": "quiet-please@gmail.com", "password": "secret123"}
    )
    assert signup.status_code == 201
    user = db.query(User).filter(User.email == "quiet-please@gmail.com").one()
    assert user.email_briefs is True, "email should be on by default"

    response = client.post(
        "/briefs/unsubscribe", json={"token": create_unsubscribe_token(user.id)}
    )
    assert response.status_code == 200

    db.expire_all()
    assert db.query(User).filter(User.email == "quiet-please@gmail.com").one().email_briefs is False


# --- Email gating --------------------------------------------------------


def _brief(content: dict, generated_by: str = "gemini") -> DailyBrief:
    # utcnow(), not date.today(): generate_brief stamps brief_date from utcnow
    # and the send guard stamps brief_emailed_on from it too. Mixing in local
    # time here makes the test disagree with production whenever the two fall
    # on different sides of midnight UTC.
    return DailyBrief(
        user_id=1, brief_date=utcnow().date(), content=content, generated_by=generated_by
    )


def _user(**kwargs) -> User:
    defaults = dict(
        id=1,
        email="creator@example.com",
        password_hash="x",
        email_briefs=True,
        brief_emailed_on=None,
    )
    defaults.update(kwargs)
    return User(**defaults)


LIVE_CONTENT = {"quiet_day": False, "opportunities": [{"id": 0}], "headline": "Something happened"}


def test_does_not_email_on_a_quiet_day(db, monkeypatch):
    """An email every morning regardless of content is how people learn to ignore it."""
    sent = []
    monkeypatch.setattr("app.workers.jobs.send_brief_email", lambda *a: sent.append(a))

    brief = _brief({"quiet_day": True, "opportunities": []})
    assert _email_brief(db, _user(), brief) is False
    assert sent == []


def test_does_not_email_when_the_user_opted_out(db, monkeypatch):
    sent = []
    monkeypatch.setattr("app.workers.jobs.send_brief_email", lambda *a: sent.append(a))

    assert _email_brief(db, _user(email_briefs=False), _brief(LIVE_CONTENT)) is False
    assert sent == []


def test_does_not_email_template_generated_prose(db, monkeypatch):
    """Showing fallback text to someone who visited is fine. Pushing it to an
    inbox as today's analysis is a different promise."""
    sent = []
    monkeypatch.setattr("app.workers.jobs.send_brief_email", lambda *a: sent.append(a))

    brief = _brief(LIVE_CONTENT, generated_by="mock-fallback")
    assert _email_brief(db, _user(), brief) is False
    assert sent == []


def test_does_not_email_twice_in_one_day(db, monkeypatch):
    """The scheduler retries; nobody wants the same brief twice."""
    sent = []
    monkeypatch.setattr("app.workers.jobs.send_brief_email", lambda *a: sent.append(a))

    user = _user(brief_emailed_on=utcnow())
    assert _email_brief(db, user, _brief(LIVE_CONTENT)) is False
    assert sent == []


def test_emails_a_real_brief(db, monkeypatch):
    sent = []
    monkeypatch.setattr("app.workers.jobs.send_brief_email", lambda *a: sent.append(a))

    user = _user()
    db.add(user)
    db.commit()

    assert _email_brief(db, user, _brief(LIVE_CONTENT)) is True
    assert len(sent) == 1
    assert sent[0][0] == "creator@example.com"
    assert user.brief_emailed_on is not None, "must be stamped so it doesn't resend"


def test_a_send_failure_does_not_stamp_or_raise(db, monkeypatch):
    """A Brevo outage must not silently mark the brief as delivered."""
    from app.services.email import EmailError

    def boom(*_args):
        raise EmailError("brevo down")

    monkeypatch.setattr("app.workers.jobs.send_brief_email", boom)

    user = _user()
    db.add(user)
    db.commit()

    assert _email_brief(db, user, _brief(LIVE_CONTENT)) is False
    assert user.brief_emailed_on is None, "a failed send must remain retryable"


def test_yesterday_s_stamp_does_not_block_today(db, monkeypatch):
    sent = []
    monkeypatch.setattr("app.workers.jobs.send_brief_email", lambda *a: sent.append(a))

    user = _user(brief_emailed_on=utcnow() - timedelta(days=1))
    db.add(user)
    db.commit()

    assert _email_brief(db, user, _brief(LIVE_CONTENT)) is True
    assert len(sent) == 1
