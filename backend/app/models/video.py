from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.utils.time import utcnow


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    views: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    likes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    comments: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    channel = relationship("Channel", back_populates="videos")
    intelligence = relationship(
        "VideoIntelligence",
        back_populates="video",
        uselist=False,
        cascade="all, delete-orphan",
    )


class VideoIntelligence(Base):
    """Derived signals for one video.

    Split from `videos` on purpose: raw YouTube facts stay immutable, interpretation
    can be recomputed or re-classified independently (Section 14 / Rule 4).
    """

    __tablename__ = "video_intelligence"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )

    # LLM-derived (semantic)
    topic: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    subtopic: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    format: Mapped[str | None] = mapped_column(String(60), nullable=True)
    angle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    classified_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Deterministic (Python only — never LLM)
    performance_ratio: Mapped[float | None] = mapped_column(Float, index=True, nullable=True)
    performance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    baseline_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_breakout: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    video = relationship("Video", back_populates="intelligence")
