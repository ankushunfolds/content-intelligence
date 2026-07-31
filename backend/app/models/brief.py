from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.utils.time import utcnow


class DailyBrief(Base):
    __tablename__ = "daily_briefs"
    __table_args__ = (UniqueConstraint("user_id", "brief_date", name="uq_user_brief_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    brief_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)

    # Structured payload: opportunities / competitor_highlights / rising_trends / headline.
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(40), default="mock", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
