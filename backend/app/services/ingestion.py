"""Phase 2 — pull channels and videos from the provider into the database.

This layer only stores facts. No interpretation happens here (Rule 4).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Channel, Video
from app.services.youtube import (
    ChannelData,
    ChannelNotFound,
    VideoData,
    YouTubeProvider,
    get_provider,
    parse_identifier,
)
from app.utils.logging import record_event
from app.utils.time import utcnow


def upsert_channel(db: Session, data: ChannelData) -> Channel:
    """Insert-or-update a channel by its YouTube ID.

    Two requests tracking the same brand-new channel at the same instant (a
    double-click, or two users adding the same competitor) both pass the
    `channel is None` check before either commits. One insert wins on the
    unique constraint; the other used to 500 with a raw IntegrityError. Catch
    that specific case and fall back to the row the other request just wrote.
    """
    channel = db.scalar(select(Channel).where(Channel.youtube_channel_id == data.youtube_channel_id))
    is_new = channel is None
    if is_new:
        channel = Channel(youtube_channel_id=data.youtube_channel_id)
        db.add(channel)

    channel.name = data.name
    channel.handle = data.handle
    channel.url = data.url
    channel.thumbnail_url = data.thumbnail_url
    channel.subscriber_count = data.subscriber_count
    channel.total_views = data.total_views
    channel.video_count = data.video_count
    channel.updated_at = utcnow()

    if not is_new:
        db.flush()
        return channel

    try:
        db.flush()
    except IntegrityError:
        # NOTE: this rolls back the whole session, not just this insert. If
        # onboarding is midway through its own-channel + competitors loop and
        # a *different* concurrent request collides on one of these channels,
        # any earlier channels already flushed in this same loop are lost too
        # (SQLAlchemy expires pending state on rollback). A SAVEPOINT would
        # scope this correctly, but SQLite's default dialect doesn't support
        # real savepoints without extra engine configuration — not worth
        # taking on for a dev-only default database. Postgres, the production
        # target, handles `db.begin_nested()` correctly out of the box if
        # this ever needs tightening. In practice this only fires when two
        # separate requests race on the *same* channel URL at the same
        # instant, which is what this fix targets and reliably resolves.
        db.rollback()
        channel = db.scalar(select(Channel).where(Channel.youtube_channel_id == data.youtube_channel_id))
        if channel is None:
            raise  # lost the race to something other than a duplicate insert — genuinely broken
    return channel


def _cached_channel(db: Session, identifier: str) -> Channel | None:
    """A channel we already hold, matched without spending API quota.

    Channels are shared across users, so in a niche cohort the same competitor
    gets added over and over — and every one of those was a fresh API call,
    up to 100 quota units each when the URL needed searching. The row is
    already in the database; re-resolving it buys nothing but a subscriber
    count that the ingestion pass refreshes anyway.

    Handle matching is case-insensitive because YouTube treats handles that
    way, and a user pasting `@Handle` should hit the row stored as `handle`.
    Deliberately no fuzzy matching on channel *name*: two channels can share a
    display name, and silently tracking the wrong competitor is a far worse
    outcome than spending a quota unit.
    """
    try:
        kind, value = parse_identifier(identifier)
    except ChannelNotFound:
        return None

    if kind == "id":
        return db.scalar(select(Channel).where(Channel.youtube_channel_id == value))
    if kind in {"handle", "search"}:
        # "search" lands here too: a /c/Slug URL is usually the @handle, which
        # is the same guess the provider makes before paying for a search.
        return db.scalar(select(Channel).where(func.lower(Channel.handle) == value.lower()))
    return None


def resolve_and_store_channel(db: Session, identifier: str, provider: YouTubeProvider | None = None) -> Channel:
    cached = _cached_channel(db, identifier)
    if cached is not None:
        return cached

    provider = provider or get_provider()
    data = provider.resolve_channel(identifier)
    return upsert_channel(db, data)


def _store_videos(db: Session, channel: Channel, videos: list[VideoData], _retried: bool = False) -> int:
    """Insert new videos, refresh metrics on ones already stored. Returns new-video count.

    Same race as `upsert_channel`, one level deeper: if two ingestion runs for
    the same channel overlap (a manual refresh landing mid-cycle with the
    background worker, say), both can see a video as "new" and both try to
    insert it. One retry — re-reading which videos actually landed — is enough
    since the retry is guaranteed to see the other transaction's commit.
    """
    existing = {
        video.youtube_video_id: video
        for video in db.scalars(select(Video).where(Video.channel_id == channel.id)).all()
    }

    new_count = 0
    latest_upload = channel.last_upload_at
    for item in videos:
        stored = existing.get(item.youtube_video_id)
        if stored is None:
            stored = Video(youtube_video_id=item.youtube_video_id, channel_id=channel.id)
            db.add(stored)
            new_count += 1
            stored.title = item.title
            stored.description = item.description
            stored.published_at = item.published_at
            stored.duration_seconds = item.duration_seconds
            stored.thumbnail_url = item.thumbnail_url
            stored.url = item.url

        # Metrics always refresh — views on an existing video move.
        stored.views = item.views
        stored.likes = item.likes
        stored.comments = item.comments
        stored.updated_at = utcnow()

        if latest_upload is None or item.published_at > latest_upload:
            latest_upload = item.published_at

    channel.last_upload_at = latest_upload
    channel.last_ingested_at = utcnow()

    try:
        db.flush()
    except IntegrityError:
        if _retried:
            raise  # not a concurrent-ingest collision — a real bug, don't hide it
        db.rollback()
        return _store_videos(db, channel, videos, _retried=True)
    return new_count


def ingest_channel(
    db: Session,
    channel: Channel,
    provider: YouTubeProvider | None = None,
    limit: int | None = None,
) -> int:
    """Fetch and store this channel's recent videos. Returns the number of new videos."""
    provider = provider or get_provider()
    limit = limit or settings.videos_per_channel

    data = ChannelData(
        youtube_channel_id=channel.youtube_channel_id,
        name=channel.name,
        handle=channel.handle,
        url=channel.url,
        thumbnail_url=channel.thumbnail_url,
        subscriber_count=channel.subscriber_count,
        total_views=channel.total_views,
        video_count=channel.video_count,
    )

    try:
        videos = provider.fetch_videos(data, limit)
    except Exception as exc:
        record_event(
            db, "ingestion.failure", f"{channel.name}: {exc}", level="error", channel_id=channel.id
        )
        raise

    new_count = _store_videos(db, channel, videos)
    db.commit()
    record_event(
        db,
        "ingestion.channel",
        f"{channel.name}: {new_count} new, {len(videos)} seen",
        channel_id=channel.id,
        new_videos=new_count,
        total_videos=len(videos),
    )
    return new_count


def ingest_channels(db: Session, channels: list[Channel], provider: YouTubeProvider | None = None) -> dict:
    """Ingest many channels, tolerating individual failures."""
    provider = provider or get_provider()
    total_new = 0
    succeeded = 0
    failures: list[str] = []

    for channel in channels:
        try:
            total_new += ingest_channel(db, channel, provider)
            succeeded += 1
        except Exception as exc:  # one bad channel must not sink the run
            failures.append(f"{channel.name}: {exc}")

    return {"channels": succeeded, "new_videos": total_new, "failures": failures}
