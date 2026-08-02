from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, briefs, channels, intelligence, trends, videos
from app.config import settings
from app.db import init_db
from app.utils.logging import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = settings.startup_problems()
    if problems:
        if settings.is_production:
            # Refuse to serve rather than run a production deploy with forgeable
            # tokens. A crashed deploy is loud and recoverable; a silently
            # insecure one is neither.
            raise RuntimeError("Unsafe production configuration: " + " | ".join(problems))
        for problem in problems:
            logger.warning("config: %s", problem)

    init_db()
    logger.info(
        "started | youtube=%s llm=%s db=%s",
        "live" if settings.using_real_youtube else "seed",
        settings.llm_provider if settings.using_real_llm else "mock",
        settings.database_url.split("://")[0],
    )
    yield


app = FastAPI(
    title="Content Intelligence API",
    version="1.0.0",
    description="Know what to create next. Before you create it.",
    lifespan=lifespan,
    # In production the interactive docs are turned off: they publish a
    # complete, machine-readable map of every route and payload shape, which is
    # a gift to anyone probing the API and buys nothing for end users. Still on
    # locally, where they're genuinely useful.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (auth.router, channels.router, videos.router, trends.router, briefs.router,
               intelligence.router, admin.router):
    app.include_router(router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "youtube_provider": "live" if settings.using_real_youtube else "seed",
        "llm_provider": settings.llm_provider if settings.using_real_llm else "mock",
        "breakout_threshold": settings.breakout_threshold,
        "trend_window_days": settings.trend_window_days,
    }
