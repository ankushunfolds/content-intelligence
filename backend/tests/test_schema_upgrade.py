"""A database created before `users.is_admin` existed must not crash on login.

`Base.metadata.create_all()` only creates missing *tables* — it silently does
nothing for a table that exists but is missing a column a newer model added.
Without `_add_missing_columns()`, every query against `users` (i.e. every
login) would 500 on an upgrade until the operator dropped and recreated the
database. This test builds exactly that pre-upgrade schema and asserts the
app heals it automatically.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

from sqlalchemy import create_engine

from app.utils.security import hash_password


def test_missing_column_is_added_without_losing_data():
    path = os.path.join(tempfile.mkdtemp(), "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email VARCHAR(320) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            niche VARCHAR(120),
            created_at DATETIME NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO users (id, email, password_hash, niche, created_at) VALUES (?, ?, ?, ?, ?)",
        (1, "legacy@example.com", hash_password("secret123"), None, "2026-01-01 00:00:00"),
    )
    conn.commit()
    conn.close()

    # Point a fresh engine at the pre-upgrade file and run the same healing
    # logic init_db() runs, without disturbing the module-level engine the
    # rest of the test suite shares.
    from sqlalchemy.orm import sessionmaker

    import app.db as db_module

    legacy_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    original_engine = db_module.engine
    db_module.engine = legacy_engine
    try:
        db_module.init_db()

        LegacySession = sessionmaker(bind=legacy_engine)
        session = LegacySession()
        from app.models import User

        user = session.query(User).filter_by(email="legacy@example.com").first()

        assert user is not None, "the pre-existing row must survive the migration"
        assert user.is_admin is False, "backfilled column must default to False, not NULL"
        from app.utils.security import verify_password

        assert verify_password("secret123", user.password_hash), "existing password must still verify"
        session.close()
    finally:
        db_module.engine = original_engine
        legacy_engine.dispose()
