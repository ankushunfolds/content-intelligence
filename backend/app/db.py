"""Database session and base model."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings
from app.utils.logging import logger

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns() -> None:
    """Bring an existing database up to date with the current models.

    `create_all()` only creates *tables that don't exist yet* — it never adds a
    column to a table that's already there. Without this, a database created
    before a model gained a field (e.g. `users.is_admin`) crashes every query
    against that table with "no such column", not just the feature that added
    it. Real schema changes belong in Alembic migrations; this is the stopgap
    that keeps the MVP's zero-setup SQLite default from breaking on upgrade.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand new table — create_all already handled it

            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue

                col_type = column.type.compile(dialect=engine.dialect)
                default_sql = _default_for(column)
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type} {default_sql}')
                )
                logger.warning(
                    "schema upgrade: added %s.%s (existing rows backfilled with the default)",
                    table.name,
                    column.name,
                )


def _default_for(column) -> str:
    if column.default is not None and getattr(column.default, "arg", None) is not None:
        arg = column.default.arg
        if isinstance(arg, bool):
            return f"DEFAULT {1 if arg else 0}"
        if isinstance(arg, (int, float)):
            return f"DEFAULT {arg}"
        if isinstance(arg, str):
            return f"DEFAULT '{arg}'"
    return "" if column.nullable else "DEFAULT 0"


def init_db() -> None:
    """Create tables, then patch any that already existed under an older schema."""
    from app import models  # noqa: F401  (registers all mappers)

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
