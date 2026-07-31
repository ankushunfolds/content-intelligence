"""Central configuration. Everything tunable lives here, read from the environment."""
from __future__ import annotations

import os
from functools import lru_cache


def _env(key: str, default: str) -> str:
    value = os.getenv(key)
    return default if value is None or value == "" else value


def _normalize_db_url(url: str) -> str:
    """Railway, Render, Heroku etc. inject a bare `postgres://` or `postgresql://`
    DSN with no driver name. SQLAlchemy needs the driver explicit (we use
    psycopg 3, not the default psycopg2), so without this every first deploy
    against a hosting platform's Postgres add-on fails at startup with an
    unhelpful "can't load plugin" error. Rewriting it here means the same
    DATABASE_URL value works whether it came from .env or a PaaS dashboard.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings:
    """Runtime settings. Deliberately plain — no magic, easy to inspect."""

    def __init__(self) -> None:
        # --- Core ---
        self.app_name: str = "Content Intelligence"
        self.env: str = _env("APP_ENV", "development")
        self.secret_key: str = _env("SECRET_KEY", "dev-secret-change-me")
        self.token_ttl_hours: int = int(_env("TOKEN_TTL_HOURS", "720"))

        # --- Database ---
        # Postgres in production; SQLite fallback so the app boots with zero setup.
        self.database_url: str = _normalize_db_url(_env("DATABASE_URL", "sqlite:///./content_intelligence.db"))

        # --- Redis / queue ---
        self.redis_url: str = _env("REDIS_URL", "redis://localhost:6379/0")

        # --- Data providers ---
        # "youtube" hits the real Data API v3; "mock" serves deterministic seed data.
        self.youtube_provider: str = _env("YOUTUBE_PROVIDER", "mock").lower()
        self.youtube_api_key: str = _env("YOUTUBE_API_KEY", "")
        self.videos_per_channel: int = int(_env("VIDEOS_PER_CHANNEL", "40"))

        # --- LLM ---
        # "mock" | "openai" | "gemini"
        self.llm_provider: str = _env("LLM_PROVIDER", "mock").lower()
        self.openai_api_key: str = _env("OPENAI_API_KEY", "")
        self.gemini_api_key: str = _env("GEMINI_API_KEY", "")
        self.llm_classify_model: str = _env("LLM_CLASSIFY_MODEL", "gpt-4o-mini")
        self.llm_brief_model: str = _env("LLM_BRIEF_MODEL", "gpt-4o-mini")

        # --- Intelligence tuning (Section 12: threshold must be configurable) ---
        self.breakout_threshold: float = float(_env("BREAKOUT_THRESHOLD", "3.0"))
        self.trend_window_days: int = int(_env("TREND_WINDOW_DAYS", "7"))
        self.min_videos_for_trend: int = int(_env("MIN_VIDEOS_FOR_TREND", "3"))
        self.max_brief_opportunities: int = int(_env("MAX_BRIEF_OPPORTUNITIES", "5"))
        self.max_brief_highlights: int = int(_env("MAX_BRIEF_HIGHLIGHTS", "3"))
        self.max_brief_trends: int = int(_env("MAX_BRIEF_TRENDS", "5"))
        # Section 11: a topic that is merely being published more, while
        # underperforming, is not an opportunity. It stays in "rising trends".
        self.opportunity_min_performance: float = float(_env("OPPORTUNITY_MIN_PERFORMANCE", "1.0"))

        # --- Limits ---
        self.max_competitors: int = int(_env("MAX_COMPETITORS", "10"))

        # --- Admin ---
        # Emails in this list get is_admin=True the moment they sign up. Empty by
        # default: /admin/* is unreachable until an operator opts in explicitly.
        self.admin_emails: set[str] = {
            e.strip().lower() for e in _env("ADMIN_EMAILS", "").split(",") if e.strip()
        }

        # --- CORS ---
        self.cors_origins: list[str] = [
            o.strip() for o in _env("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
        ]

    @property
    def using_real_youtube(self) -> bool:
        return self.youtube_provider == "youtube" and bool(self.youtube_api_key)

    @property
    def using_real_llm(self) -> bool:
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        if self.llm_provider == "gemini":
            return bool(self.gemini_api_key)
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
