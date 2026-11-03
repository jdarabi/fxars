"""FIX-10-PG: PostgreSQL migration runner.

منبع حقیقت: postgres_schema.sql (idempotent).
upgrade_postgres(db) → CREATE TABLE IF NOT EXISTS ... + INSERT schema_migrations.
"""
from __future__ import annotations

from dataclasses import dataclass
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
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"postgres_schema.sql not found at {SCHEMA_PATH}")
    return PostgresMigration(
        version=1,
        name="initial_postgres_schema",
        up_sql=SCHEMA_PATH.read_text(encoding="utf-8"),
    )


def _ensure_meta_table(db) -> None:
    db.executescript(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " applied_at TIMESTAMPTZ NOT NULL)"
    )


def upgrade_postgres(db, *, target: int | None = None) -> dict:
    _ensure_meta_table(db)
    migrations = [load_initial_migration()]
    applied = {int(row["version"]) for row in db.query("SELECT version FROM schema_migrations")}
    pending = [m for m in migrations if m.version not in applied]
    if target is not None:
        pending = [m for m in pending if m.version <= target]
    pending.sort(key=lambda m: m.version)

    applied_names: list[str] = []
    for migration in pending:
        db.executescript(migration.up_sql)
        db.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) "
            "VALUES (%s, %s, %s) ON CONFLICT (version) DO NOTHING",
            (migration.version, migration.name, format_ts(utcnow())),
        )
        applied_names.append(migration.name)

    current = int(db.scalar("SELECT COALESCE(MAX(version), 0) FROM schema_migrations") or 0)
    return {"applied": applied_names, "current_version": current}


def history_postgres(db) -> list[dict]:
    _ensure_meta_table(db)
    rows = db.query("SELECT version, name, applied_at FROM schema_migrations ORDER BY version")
    return [dict(row) for row in rows]