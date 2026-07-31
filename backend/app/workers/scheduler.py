"""Worker entrypoint.

    python -m app.workers.scheduler            # loop forever
    python -m app.workers.scheduler --once     # single cycle, then exit
    python -m app.workers.scheduler --job ingest

Deliberately a loop and not Celery: an MVP with a handful of creators does not
need a broker topology, and this is trivial to reason about and to replace.
Redis is used only for a lock, so two instances can't double-run.
"""
from __future__ import annotations

import argparse
import sys
import time

from app.config import settings
from app.db import init_db
from app.utils.logging import logger
from app.workers import jobs

INTERVAL_SECONDS = 60 * 60 * 6  # four cycles a day is plenty for YouTube data

JOBS = {
    "ingest": jobs.job_ingest_channels,
    "analyse": jobs.job_analyse_videos,
    "trends": jobs.job_compute_trends,
    "briefs": jobs.job_generate_briefs,
    "all": jobs.run_daily_cycle,
}


def _lock():
    """Best-effort distributed lock. No Redis? Run anyway — a single worker is the default."""
    try:
        import redis

        client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
        if client.set("ci:worker:lock", "1", nx=True, ex=INTERVAL_SECONDS - 60):
            return client
        logger.info("another worker holds the lock; skipping this cycle")
        return None
    except Exception as exc:
        logger.info("redis unavailable (%s) — running without a lock", exc)
        return "no-redis"


def run_cycle(job: str = "all") -> None:
    lock = _lock()
    if lock is None:
        return
    try:
        result = JOBS[job]()
        logger.info("cycle complete: %s", result)
    except Exception:
        logger.exception("cycle failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Content Intelligence worker")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--job", default="all", choices=sorted(JOBS), help="which job to run")
    parser.add_argument("--interval", type=int, default=INTERVAL_SECONDS)
    args = parser.parse_args()

    init_db()

    if args.once:
        run_cycle(args.job)
        return 0

    logger.info("worker started; interval=%ss job=%s", args.interval, args.job)
    while True:
        run_cycle(args.job)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
