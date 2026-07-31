#!/usr/bin/env python3
"""Create a demo account with tracked channels and a full intelligence run.

    python scripts/seed_demo.py

Prints the login you can use immediately. Uses whatever providers your .env
selects — with the defaults that means seed data and no API spend.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Channel, TrackedChannel, User
from app.services import ingestion, pipeline
from app.utils.security import hash_password

EMAIL = "demo@contentintelligence.app"
PASSWORD = "demo1234"

OWN = "@yourchannel"
COMPETITORS = [
    "@signalstudio",
    "@thebuildlog",
    "@creatorlab",
    "@deepworkmedia",
    "@practicalai",
    "@growthnotes",
]


def main() -> int:
    init_db()
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == EMAIL))
        if user is None:
            user = User(email=EMAIL, password_hash=hash_password(PASSWORD), niche="AI / Technology")
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"created user {EMAIL}")
        else:
            print(f"reusing existing user {EMAIL}")

        for url, kind in [(OWN, "own")] + [(c, "competitor") for c in COMPETITORS]:
            channel = ingestion.resolve_and_store_channel(db, url)
            existing = db.scalar(
                select(TrackedChannel).where(
                    TrackedChannel.user_id == user.id, TrackedChannel.channel_id == channel.id
                )
            )
            if existing is None:
                db.add(TrackedChannel(user_id=user.id, channel_id=channel.id, type=kind))
            print(f"  tracking {channel.name} ({kind})")
        db.commit()

        print("\nrunning the pipeline…")
        summary = pipeline.run_pipeline(db, user.id)
        for key, value in summary.items():
            print(f"  {key:>20}: {value}")

        print(f"\nDone. Sign in with {EMAIL} / {PASSWORD}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
