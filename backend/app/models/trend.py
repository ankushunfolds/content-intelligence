from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.utils.time import utcnow


class Trend(Base):
    """A topic/subtopic pair scored over a window, per user's tracked set."""

    __tablename__ = "trends"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    topic: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    subtopic: Mapped[str | None] = mapped_column(String(120), nullable=True)

    trend_score: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    volume_growth: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # fraction, 0.43 == +43%
    video_velocity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # videos/day in window
    avg_performance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # × baseline
    creator_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    video_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    breakout_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    top_format: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Every component that fed the score, so the number is inspectable (Section 11).
    components: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True, nullable=False)
