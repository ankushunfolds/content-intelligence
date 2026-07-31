from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.utils.time import utcnow


class Channel(Base):
    """A YouTube channel. Shared across users — two creators may track the same competitor."""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_channel_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(120), nullable=True)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    subscriber_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_views: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    video_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_upload_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    videos = relationship("Video", back_populates="channel", cascade="all, delete-orphan")


class TrackedChannel(Base):
    """Join table: which channels a given user watches, and in what role."""

    __tablename__ = "tracked_channels"
    __table_args__ = (UniqueConstraint("user_id", "channel_id", name="uq_user_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # "own" | "competitor"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    channel = relationship("Channel")
