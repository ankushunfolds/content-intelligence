"""Central configuration. Everything tunable lives here, read from the environment."""
from __future__ import annotations

import os
from functools import lru_cache


def _env(key: str, default: str) -> str:
    value = os.getenv(key)
    return default if value is None or value == "" else value


def _optional_int(key: str) -> int | None:
    """Unset or blank means "no opinion" — distinct from 0, which is a real
    setting. Used for knobs where omitting the field entirely is meaningfully
    different from sending a zero (see the thinking budgets below).
    """
    value = os.getenv(key)
    if value is None or not value.strip():
        return None
    return int(value)


# Sentinel so the startup check can recognise "nobody set a real one". Every
# auth, email-verification and password-reset token is signed with the secret
# key, so if this placeholder is ever live in production anyone who reads this
# repo can mint a valid session for any account.
DEV_SECRET_KEY = "dev-secret-change-me"


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
        self.secret_key: str = _env("SECRET_KEY", DEV_SECRET_KEY)
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
        # Defaults are Gemini names, matching the provider actually used in
        # production. They were OpenAI names until Aug 2026, which meant a
        # Gemini deployment that didn't override them fell through to a
        # hardcoded default in llm.py — and when that default retired, every
        # brief silently degraded to template text. Defaults should describe
        # the deployment they're used by.
        self.llm_classify_model: str = _env("LLM_CLASSIFY_MODEL", "gemini-3.5-flash-lite")
        self.llm_brief_model: str = _env("LLM_BRIEF_MODEL", "gemini-3.5-flash")

        # Gemini 3.x thinking tokens bill at the *output* rate, so on a model
        # that reasons this is a real cost lever. But it is not universally
        # supported: measured 2 Aug 2026, gemini-3.5-flash-lite returns 400
        # INVALID_ARGUMENT if thinkingConfig is present at all, and reports
        # thoughtsTokenCount=0 regardless — it doesn't reason, so there was
        # never anything to disable.
        #
        # Hence: blank by default, meaning "send no thinkingConfig and let the
        # model do whatever it does". Set 0 (off) or -1 (model decides) only
        # when classification is pointed at a model that actually thinks.
        self.llm_classify_thinking_budget: int | None = _optional_int("LLM_CLASSIFY_THINKING_BUDGET")
        self.llm_brief_thinking_budget: int | None = _optional_int("LLM_BRIEF_THINKING_BUDGET")

        # Transient-failure retries before degrading to mock output. Kept low
        # on purpose: a brief is one call and worth waiting a few seconds for,
        # but classification runs many batches per pipeline run, so generous
        # retries during a real outage would turn into minutes of sleeping for
        # a result that was going to fall back anyway.
        self.llm_max_retries: int = int(_env("LLM_MAX_RETRIES", "2"))
        self.llm_retry_base_delay: float = float(_env("LLM_RETRY_BASE_DELAY", "1.0"))

        # How long a brief that fell back to template text is served before a
        # read retries the narration. Briefs cache for a day, so without this a
        # momentary outage is served for up to 24 hours; with it, recovery
        # takes minutes. The interval is the safety valve — it caps a sustained
        # outage at one attempt per user per interval instead of one per page
        # load, which would be slowest and priciest exactly when the provider
        # is already in trouble.
        self.brief_degraded_retry_minutes: int = int(_env("BRIEF_DEGRADED_RETRY_MINUTES", "15"))

        # --- Intelligence tuning (Section 12: threshold must be configurable) ---
        self.breakout_threshold: float = float(_env("BREAKOUT_THRESHOLD", "3.0"))
        # Videos at or under this length are treated as Shorts and scored
        # against a separate baseline. 180s matches YouTube's own Shorts
        # ceiling. Duration is the only format signal the API gives us.
        self.shorts_max_seconds: int = int(_env("SHORTS_MAX_SECONDS", "180"))
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
        # Ceiling on how many videos one pipeline run will send to the LLM.
        # Onboarding with 10 channels can surface 400+ unclassified videos at
        # once, which is 20+ LLM calls in a single request — enough to trip a
        # free-tier quota on the very first run. Anything left over is picked
        # up by the next run, so nothing is lost, it just arrives later.
        self.max_classify_per_run: int = int(_env("MAX_CLASSIFY_PER_RUN", "120"))

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

        # --- Email (verification) ---
        # Brevo (formerly Sendinblue) transactional email API. Free tier is
        # generous enough for a beta cohort — see services/email.py.
        self.brevo_api_key: str = _env("BREVO_API_KEY", "")
        self.brevo_sender_email: str = _env("BREVO_SENDER_EMAIL", "no-reply@contentintelligence.app")
        self.brevo_sender_name: str = _env("BREVO_SENDER_NAME", "Content Intelligence")
        # Where verification links point. Must be the frontend's public URL.
        self.frontend_url: str = _env("FRONTEND_URL", "http://localhost:3000")
        # False during the initial beta: unverified users can still use the
        # product, they just see a banner. Flip to True once Brevo is
        # confirmed working end-to-end and you want a hard gate.
        self.require_email_verification: bool = _env("REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true"

        # --- Monitoring ---
        # Shared secret for GET /admin/health-summary — lets an external
        # scheduled check read error counts without a logged-in admin
        # session. Empty by default: the endpoint 404s until you set this,
        # same "opt-in by setting a var" pattern as ADMIN_EMAILS.
        self.admin_monitor_key: str = _env("ADMIN_MONITOR_KEY", "")

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}

    def startup_problems(self) -> list[str]:
        """Misconfigurations that are dangerous in production.

        Returned rather than raised so the caller decides how loud to be: fatal
        in production, a warning locally (where the dev defaults are the point).
        """
        problems: list[str] = []
        if self.secret_key == DEV_SECRET_KEY:
            problems.append(
                "SECRET_KEY is still the built-in development value — every session, "
                "email-verification and password-reset token is forgeable. Set SECRET_KEY."
            )
        if any(o == "*" for o in self.cors_origins):
            problems.append(
                "CORS_ORIGINS is '*' while credentials are allowed — any site could call "
                "the API with a logged-in user's browser. Set it to the frontend's URL."
            )
        return problems

    def degraded_modes(self) -> list[str]:
        """Places the app is serving stand-in data while looking entirely healthy.

        Distinct from startup_problems(), which is fatal in production: nothing
        here is unsafe, and refusing to boot over it would trade a misleading
        product for no product at all. But these are not warnings to shrug at.
        A mock provider returns plausible, well-formed, confident output — it
        throws nothing, logs nothing, and renders identically to the real
        thing. That is precisely the shape of the 2 Aug incident, where a
        retired model routed every brief through MockLLM for hours with no
        error surfaced to anyone.

        The YouTube case is worse than the LLM one. Seed data means the
        competitor set, the view counts and the breakout multipliers are all
        invented, so a user makes real content decisions on fiction. Returned
        here so /admin/health-summary can report it and the monitor can catch
        a deploy that quietly came up on defaults.
        """
        modes: list[str] = []
        if not self.using_real_youtube:
            modes.append(
                f"YOUTUBE_PROVIDER={self.youtube_provider!r} with "
                f"{'a key set' if self.youtube_api_key else 'NO api key'} — channel data, view "
                "counts and breakout multipliers are deterministic seed data, not real YouTube."
            )
        if not self.using_real_llm:
            modes.append(
                f"LLM_PROVIDER={self.llm_provider!r} — briefs and classifications are "
                "template-generated, not model-generated."
            )
        return modes

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
