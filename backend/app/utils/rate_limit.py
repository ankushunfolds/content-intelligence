"""In-process rate limiting for auth endpoints.

Deliberately in-memory, not Redis-backed: the app runs as a single uvicorn
worker (see Procfile — no `--workers` flag), so there's exactly one process
holding this state and no cross-process consistency problem to solve. If the
backend is ever scaled to multiple replicas, this stops being correct (each
replica would track its own counts) and should move to Redis at that point —
`settings.redis_url` already exists for the worker queue and could be reused.

Fixed-window counter per (bucket, identifier). Simple on purpose: this exists
to stop casual abuse (scripted signup spam, credential-stuffing attempts
against login), not to withstand a determined attacker rotating IPs.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

# {(bucket, identifier): [(window_start, count)]}
_hits: dict[tuple[str, str], list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    # Railway (and most PaaS) sit behind a proxy that sets this; fall back to
    # the direct connection for local dev where there's no proxy in front.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request, bucket: str, *, max_attempts: int, window_seconds: int) -> None:
    """Raise 429 if `bucket` has seen more than `max_attempts` hits from this
    IP within the last `window_seconds`. Otherwise records this hit."""
    identifier = _client_ip(request)
    key = (bucket, identifier)
    now = time.monotonic()
    cutoff = now - window_seconds

    recent = [t for t in _hits[key] if t > cutoff]
    if len(recent) >= max_attempts:
        retry_after = int(recent[0] + window_seconds - now) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many attempts. Please try again in {retry_after}s.",
        )

    recent.append(now)
    _hits[key] = recent
