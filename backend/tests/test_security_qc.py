"""Regression tests for the production QC pass.

Each test here pins a specific problem that was found by auditing the deployed
app, so that fixing it once means it stays fixed.
"""
from __future__ import annotations

import pytest

from app.config import DEV_SECRET_KEY, Settings
from app.utils import rate_limit
from app.utils.security import (
    create_reset_token,
    create_token,
    create_verify_token,
    decode_reset_token,
    decode_token,
    decode_verify_token,
    hash_password,
)


# --- Token hygiene -------------------------------------------------------


@pytest.mark.parametrize(
    "junk",
    [
        "",
        "garbage",
        "not-even-two-parts",
        "garbage.token",  # second half isn't valid base64
        "a.b.c",
        "!!!.???",
        "." * 5,
    ],
)
def test_malformed_tokens_are_rejected_not_crashed(junk):
    """A truncated link or a fuzzing bot must produce a clean rejection.

    These used to raise binascii.Error out of the base64 decode, which surfaced
    as a 500 from /auth/verify and /auth/reset-password.
    """
    assert decode_token(junk) is None
    assert decode_verify_token(junk) is None
    assert decode_reset_token(junk, hash_password("whatever")) is None


def test_token_purposes_are_not_interchangeable():
    """A verification or reset link must never work as a login session."""
    pwd = hash_password("secret123")
    assert decode_token(create_verify_token(1)) is None
    assert decode_token(create_reset_token(1, pwd)) is None
    assert decode_verify_token(create_token(1)) is None
    assert decode_reset_token(create_token(1), pwd) is None


def test_reset_token_dies_once_the_password_changes():
    """Reset links are single-use: the new hash no longer matches the token."""
    old = hash_password("original")
    token = create_reset_token(7, old)
    assert decode_reset_token(token, old) == 7

    new = hash_password("changed")
    assert decode_reset_token(token, new) is None


# --- Configuration safety ------------------------------------------------


def test_production_refuses_the_development_secret_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", DEV_SECRET_KEY)
    problems = Settings().startup_problems()
    assert any("SECRET_KEY" in p for p in problems)


def test_production_flags_wildcard_cors(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "a-real-secret")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    problems = Settings().startup_problems()
    assert any("CORS" in p for p in problems)


def test_a_properly_configured_production_env_has_no_problems(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "a-real-secret")
    monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
    assert Settings().startup_problems() == []


# --- Rate limiting -------------------------------------------------------


def test_signup_is_rate_limited(client):
    """Sixth signup from the same IP inside the window is refused."""
    codes = [
        client.post(
            "/auth/signup", json={"email": f"spam{i}@gmail.com", "password": "secret123"}
        ).status_code
        for i in range(7)
    ]
    assert 429 in codes, codes


def test_refresh_is_rate_limited_per_user(client, auth):
    """Refresh re-ingests from YouTube and calls the LLM, so it must be capped.

    Previously unlimited: holding down the Refresh button would burn the day's
    API quota for every user on the deployment.
    """
    codes = [client.post("/intelligence/refresh", headers=auth).status_code for _ in range(7)]
    assert 429 in codes, codes


def test_rate_limit_state_does_not_grow_without_bound():
    """Stale per-IP entries are reclaimed instead of accumulating forever.

    The guarantee is bounded memory, not immediate collection: an entry is kept
    until it is older than the longest window any caller uses, because the
    sweep can't know which window a given key belongs to. So this back-dates
    the hits to prove they do eventually get dropped.
    """
    import time

    rate_limit._hits.clear()
    rate_limit._calls_since_sweep = 0

    class _Req:
        def __init__(self, ip):
            self.headers = {"x-forwarded-for": ip}
            self.client = None

    # Simulate a horde of one-off visitors from a while ago.
    old = time.monotonic() - rate_limit._MAX_WINDOW_SECONDS - 60
    for i in range(rate_limit._SWEEP_EVERY):
        rate_limit._hits[("probe", f"10.0.{i // 256}.{i % 256}")] = [old]
    assert len(rate_limit._hits) == rate_limit._SWEEP_EVERY

    # One more call crosses the sweep threshold and collects them.
    rate_limit._calls_since_sweep = rate_limit._SWEEP_EVERY - 1
    rate_limit.enforce_rate_limit(_Req("10.9.9.9"), "probe", max_attempts=99, window_seconds=60)

    assert len(rate_limit._hits) == 1, len(rate_limit._hits)


# --- Access control ------------------------------------------------------


def test_health_summary_hidden_without_the_key(client):
    assert client.get("/admin/health-summary").status_code in (404, 422)
    assert client.get("/admin/health-summary?key=wrong").status_code == 404


def test_admin_routes_require_admin_not_just_login(client, auth):
    """Being signed up must not be enough to read the global event log."""
    assert client.get("/admin/events", headers=auth).status_code == 403
    assert client.get("/admin/stats", headers=auth).status_code == 403


def test_users_cannot_read_another_users_data(client, auth):
    """Second user must not see the first user's channels or trends."""
    other = client.post(
        "/auth/signup", json={"email": "someone-else@gmail.com", "password": "secret123"}
    )
    assert other.status_code == 201, other.text
    other_auth = {"Authorization": f"Bearer {other.json()['access_token']}"}

    assert client.get("/channels/tracked", headers=other_auth).json() == []
    assert client.get("/trends", headers=other_auth).json() == []


def test_forgot_password_does_not_reveal_whether_an_account_exists(client):
    known = client.post("/auth/forgot-password", json={"email": "creator@example.com"})
    unknown = client.post("/auth/forgot-password", json={"email": "nobody-here@gmail.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
