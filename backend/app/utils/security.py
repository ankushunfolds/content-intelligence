"""Simple auth (Section 20: 'authentication can be simple initially').

PBKDF2 password hashing from the stdlib plus signed, expiring tokens — no extra
dependencies, no bcrypt build step, and swappable for real JWT later.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time

from app.config import settings

_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def password_fingerprint(password_hash: str) -> str:
    """A short, non-reversible marker tying a token to one password.

    The tail of the stored PBKDF2 digest. It is already a hash, so this leaks
    nothing useful, but it changes whenever the password changes — which is
    what lets us invalidate sessions without a server-side session store.
    """
    return password_hash[-16:]


def create_token(user_id: int, password_hash: str) -> str:
    payload = {
        "sub": user_id,
        "pwd": password_fingerprint(password_hash),
        "exp": int(time.time()) + settings.token_ttl_hours * 3600,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def decode_token(token: str) -> int | None:
    """Return the user id, or None if the token is malformed, forged, or expired.

    This does NOT prove the session is still current — see `token_is_current`.
    """
    payload = _decode_signed(token)
    if payload is None or payload.get("purpose") is not None:
        # A verify-email token carries a "purpose" claim (see below) so it
        # can never be replayed as a login/auth token, and vice versa.
        return None
    return int(payload["sub"])


def token_is_current(token: str, password_hash: str) -> bool:
    """Whether this session predates the account's current password.

    Tokens are stateless, so without this a stolen one stays valid for its
    full lifetime and changing the password does nothing to evict the thief.
    Binding the token to the password hash means any password change — a
    reset, or a future "change password" — silently invalidates every session
    issued before it.

    Tokens minted before this claim existed have no "pwd" and are treated as
    stale, which forces one clean re-login on deploy.
    """
    payload = _decode_signed(token)
    if payload is None:
        return False
    return hmac.compare_digest(payload.get("pwd") or "", password_fingerprint(password_hash))


_VERIFY_TOKEN_TTL_HOURS = 24


def create_verify_token(user_id: int) -> str:
    payload = {
        "sub": user_id,
        "purpose": "verify_email",
        "exp": int(time.time()) + _VERIFY_TOKEN_TTL_HOURS * 3600,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def decode_verify_token(token: str) -> int | None:
    """Return the user id from a verify-email token, or None if invalid/expired/wrong purpose."""
    payload = _decode_signed(token)
    if payload is None or payload.get("purpose") != "verify_email":
        return None
    return int(payload["sub"])


def create_unsubscribe_token(user_id: int) -> str:
    """Long-lived by design: it sits in the footer of every brief email, and a
    link that expires turns "stop emailing me" into "log in and find a setting".
    Scoped by purpose so it can only ever turn emails off, never authenticate.
    """
    payload = {
        "sub": user_id,
        "purpose": "unsubscribe",
        "exp": int(time.time()) + 365 * 24 * 3600,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def decode_unsubscribe_token(token: str) -> int | None:
    payload = _decode_signed(token)
    if payload is None or payload.get("purpose") != "unsubscribe":
        return None
    return int(payload["sub"])


_RESET_TOKEN_TTL_HOURS = 1


def create_reset_token(user_id: int, password_hash: str) -> str:
    """The current password hash is folded into the payload so that once a
    reset link is used (or the password is changed any other way), the old
    token stops decoding — the hash it was signed against no longer matches,
    so it can't be replayed even though it hasn't technically expired yet.
    """
    payload = {
        "sub": user_id,
        "purpose": "reset_password",
        "pwd": password_hash[-16:],
        "exp": int(time.time()) + _RESET_TOKEN_TTL_HOURS * 3600,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def decode_reset_token(token: str, current_password_hash: str) -> int | None:
    """Return the user id from a reset-password token, or None if invalid,
    expired, wrong purpose, or already consumed (password changed since)."""
    payload = _decode_signed(token)
    if payload is None or payload.get("purpose") != "reset_password":
        return None
    if payload.get("pwd") != current_password_hash[-16:]:
        return None
    return int(payload["sub"])


def _decode_signed(token: str) -> dict | None:
    try:
        body, signature = token.split(".")
        expected = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(signature), expected):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error):
        # Any malformed input (bad base64, wrong segment count, non-JSON body,
        # etc.) is just an invalid token — not a server error. A user pasting
        # a truncated link or a bot fuzzing the endpoint should get a clean
        # 400 from the caller, not a 500.
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload
