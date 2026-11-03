"""PostgreSQL migration runner (P4-3-ext).

Mirrors fxars/storage/migrations.py but for Postgres:
- loads postgres_schema.sql as the initial migration
- uses psycopg if available; otherwise tests skip
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fxars.core.timeutil import format_ts, utcnow


SCHEMA_PATH = Path(__file__).with_name("postgres_schema.sql")


@dataclass(frozen=True)
class PostgresMigration:
    version: int
    name: str
    up_sql: str
    down_sql: str = ""


def load_initial_migration() -> PostgresMigration:
    """Load postgres_schema.sql as migration version 1."""
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"postgres_schema.sql not found at {SCHEMA_PATH}")
    return PostgresMigration(
        version=1,
        name="initial_postgres_schema",
        up_sql=SCHEMA_PATH.read_text(encoding="utf-8"),
        down_sql="",
    )


def upgrade_postgres(db, *, target: int | None = None) -> dict:
    """Apply pending Postgres migrations.

    Uses the same schema_migrations table as the SQLite runner.
    Idempotent: CREATE TABLE IF NOT EXISTS in the schema makes re-runs safe.
    """
    db.migrate()  # ensure schema_migrations exists
    migrations = [load_initial_migration()]
    applied = {int(row["version"]) for row in db.query("SELECT version FROM schema_migrations")}
    pending = [m for m in migrations if m.version not in applied]
    if target is not None:
        pending = [m for m in pending if m.version <= target]
    pending.sort(key=lambda m: m.version)

    applied_names: list[str] = []
    for migration in pending:
        # executescript splits on ';' and runs each statement
        db.executescript(migration.up_sql)
        db.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (version) DO UPDATE SET name=EXCLUDED.name, applied_at=EXCLUDED.applied_at",
            (migration.version, migration.name, format_ts(utcnow())),
        )
        applied_names.append(migration.name)

    return {
        "applied": applied_names,
        "current_version": int(db.scalar("SELECT COALESCE(MAX(version), 0) FROM schema_migrations") or 0),
    }