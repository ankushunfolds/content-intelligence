from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.utils.time import utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    niche: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Gates /admin/*. Never set via a request body — only by ADMIN_EMAILS at
    # signup, or directly in the database. See api/deps.require_admin.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set True only by /auth/verify consuming a valid token. See
    # utils.security.create_verify_token and services/email.py.
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Throttles /auth/resend-verification (see api/auth.py) so a user can't
    # hammer the Brevo free-tier quota by re-requesting the same email.
    verification_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
