from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.utils.time import utcnow


class EventLog(Base):
    """Minimal observability (Section 28). One row per notable operation or failure."""

    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info", index=True, nullable=False)
    message: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True, nullable=False)
