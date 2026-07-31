"""Section 28 — basic observability from day one. Logs to stdout and the event_log table."""
from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from time import perf_counter

from sqlalchemy.orm import Session

from app.utils.time import utcnow

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)

logger = logging.getLogger("content-intelligence")


def record_event(
    db: Session | None,
    kind: str,
    message: str = "",
    *,
    level: str = "info",
    duration_ms: float | None = None,
    cost_usd: float | None = None,
    **meta,
) -> None:
    line = f"[{kind}] {message}"
    getattr(logger, "error" if level == "error" else "info")(line)
    if db is None:
        return
    try:
        # Error events are frequently logged right after the same session hit a
        # failed flush/commit elsewhere (e.g. an ingestion race). SQLAlchemy
        # leaves the session unusable until an explicit rollback, so without
        # this, logging the original failure raises a second, unrelated
        # PendingRollbackError that masks it. A rollback on an already-clean
        # session is a harmless no-op, so this is safe to do unconditionally.
        db.rollback()

        from app.models import EventLog

        db.add(
            EventLog(
                kind=kind,
                level=level,
                message=message[:1024],
                duration_ms=duration_ms,
                cost_usd=cost_usd,
                meta=meta or {},
                created_at=utcnow(),
            )
        )
        db.commit()
    except Exception:  # observability must never break the request
        db.rollback()
        logger.exception("failed to persist event")


@contextmanager
def timed(db: Session | None, kind: str, message: str = "", **meta):
    """Time a block and log it, capturing failures as error events."""
    start = perf_counter()
    try:
        yield
    except Exception as exc:
        record_event(
            db,
            kind,
            f"{message} failed: {exc}",
            level="error",
            duration_ms=(perf_counter() - start) * 1000,
            **meta,
        )
        raise
    record_event(db, kind, message, duration_ms=(perf_counter() - start) * 1000, **meta)
