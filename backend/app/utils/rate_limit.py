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


# Entries are only pruned when their own key is hit again, so a key that is
# never seen again would sit in the dict forever. Every distinct client IP that
# ever touches an auth endpoint creates one — including scanners and bots — so
# left alone this grows without bound for the life of the process. Sweeping
# occasionally keeps it proportional to *recent* traffic instead of all-time.
_SWEEP_EVERY = 500
_calls_since_sweep = 0


def _sweep(now: float) -> None:
    """Drop keys whose most recent hit is older than any window we use."""
    stale = [key for key, hits in _hits.items() if not hits or now - hits[-1] > _MAX_WINDOW_SECONDS]
    for key in stale:
        del _hits[key]


# Longest window any caller uses (the 1h refresh limit), with headroom.
_MAX_WINDOW_SECONDS = 3600 * 2


def enforce_rate_limit(
    request: Request,
    bucket: str,
    *,
    max_attempts: int,
    window_seconds: int,
    identifier: str | None = None,
) -> None:
    """Raise 429 if `bucket` has seen more than `max_attempts` hits from this
    caller within the last `window_seconds`. Otherwise records this hit.

    `identifier` defaults to the client IP. Pass an explicit one (e.g.
    `user:42`) for limits that should follow the account rather than the
    network — otherwise everyone behind one office NAT shares a budget.
    """
    global _calls_since_sweep

    identifier = identifier or _client_ip(request)
    key = (bucket, identifier)
    now = time.monotonic()
    cutoff = now - window_seconds

    _calls_since_sweep += 1
    if _calls_since_sweep >= _SWEEP_EVERY:
        _calls_since_sweep = 0
        _sweep(now)

    recent = [t for t in _hits[key] if t > cutoff]
    if len(recent) >= max_attempts:
        retry_after = int(recent[0] + window_seconds - now) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many attempts. Please try again in {retry_after}s.",
        )

    recent.append(now)
    _hits[key] = recent
