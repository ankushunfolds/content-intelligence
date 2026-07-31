from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC. Consistent across SQLite and Postgres without timezone headaches."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def days_ago(n: int) -> datetime:
    from datetime import timedelta

    return utcnow() - timedelta(days=n)


def parse_iso(value: str) -> datetime:
    """Parse a YouTube ISO-8601 timestamp into naive UTC."""
    cleaned = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_iso_duration(value: str) -> int:
    """Convert an ISO-8601 duration (PT12M4S) to seconds."""
    import re

    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return 0
    days, hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds
