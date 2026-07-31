"""Simple auth (Section 20: 'authentication can be simple initially').

PBKDF2 password hashing from the stdlib plus signed, expiring tokens — no extra
dependencies, no bcrypt build step, and swappable for real JWT later.
"""
from __future__ import annotations

import base64
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


def create_token(user_id: int) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + settings.token_ttl_hours * 3600}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def decode_token(token: str) -> int | None:
    """Return the user id, or None if the token is malformed, forged, or expired."""
    try:
        body, signature = token.split(".")
    except ValueError:
        return None
    expected = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_unb64(signature), expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return int(payload["sub"])
