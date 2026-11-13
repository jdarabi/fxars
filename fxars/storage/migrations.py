"""Migration framework with up/down and version history.

Each migration is a (version, name, up_sql, down_sql) tuple. The runner
applies missing migrations in order and records them in schema_migrations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fxars.core.timeutil import format_ts, utcnow
from fxars.storage.db import Database


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up_sql: str
    down_sql: str = ""


_INITIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    instrument_id TEXT PRIMARY KEY,
    version       INTEGER NOT NULL,
    payload       TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_sources (
    source_id  TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candles (
    instrument_id  TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    timeframe      TEXT NOT NULL,
    open_time      TEXT NOT NULL,
    revision       INTEGER NOT NULL,
    is_closed      INTEGER NOT NULL,
    quality_status TEXT NOT NULL,
    available_at   TEXT NOT NULL,
    ingested_at    TEXT NOT NULL,
    payload        TEXT NOT NULL,
    PRIMARY KEY (instrument_id, source_id, timeframe, open_time, revision)
);
CREATE INDEX IF NOT EXISTS idx_candles_range ON candles (instrument_id, timeframe, open_time);
CREATE INDEX IF NOT EXISTS idx_candles_available ON candles (instrument_id, timeframe, available_at);
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id            TEXT PRIMARY KEY,
    instrument_id     TEXT NOT NULL,
    timeframe         TEXT NOT NULL,
    as_of             TEXT NOT NULL,
    data_snapshot_id  TEXT NOT NULL,
    config_hash       TEXT NOT NULL,
    code_version      TEXT NOT NULL,
    model_version     TEXT NOT NULL,
    status            TEXT NOT NULL,
    correlation_id    TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    result_hash       TEXT NOT NULL,
    evidence_count    INTEGER NOT NULL,
    decision          TEXT NOT NULL,
    data_quality      TEXT NOT NULL,
    error             TEXT
);
CREATE TABLE IF NOT EXISTS evidences (
    evidence_id    TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    module_id      TEXT NOT NULL,
    family         TEXT NOT NULL,
    observed_at    TEXT NOT NULL,
    available_at   TEXT NOT NULL,
    direction      TEXT NOT NULL,
    strength       REAL NOT NULL,
    payload        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id      TEXT PRIMARY KEY,
    instrument_id    TEXT NOT NULL,
    timeframe        TEXT NOT NULL,
    direction        TEXT NOT NULL,
    status           TEXT NOT NULL,
    expiry_at        TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    risk_decision_id TEXT,
    analysis_run_id  TEXT NOT NULL,
    payload          TEXT NOT NULL
);
"""


_CLOSED_TRADES = """
CREATE TABLE IF NOT EXISTS closed_trades (
    trade_id      TEXT PRIMARY KEY,
    intent_id     TEXT NOT NULL UNIQUE,
    tenant_id     TEXT NOT NULL DEFAULT 'default',
    instrument_id TEXT NOT NULL,
    side          TEXT NOT NULL,
    scenario_id   TEXT,
    closed_at     TEXT NOT NULL,
    volume        TEXT NOT NULL,
    net_profit    TEXT NOT NULL,
    payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_closed_trades_tenant ON closed_trades (tenant_id, closed_at);
CREATE INDEX IF NOT EXISTS idx_closed_trades_instrument ON closed_trades (instrument_id, closed_at);
"""

_SUPPLEMENT_GOVERNANCE = """
CREATE TABLE IF NOT EXISTS decision_provenance (
    record_id       TEXT PRIMARY KEY,
    decision_id     TEXT NOT NULL,
    analysis_run_id TEXT NOT NULL,
    scenario_id     TEXT,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    created_at      TEXT NOT NULL,
    prev_hash       TEXT NOT NULL,
    record_hash     TEXT NOT NULL,
    payload         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provenance_run ON decision_provenance (analysis_run_id);
CREATE INDEX IF NOT EXISTS idx_provenance_decision ON decision_provenance (decision_id);
CREATE TABLE IF NOT EXISTS policy_registry (
    policy_id  TEXT NOT NULL,
    version    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    status     TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload    TEXT NOT NULL,
    PRIMARY KEY (policy_id, version)
);
CREATE INDEX IF NOT EXISTS idx_policy_kind ON policy_registry (kind, status);
CREATE TABLE IF NOT EXISTS decision_journal (
    entry_id        TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    analysis_run_id TEXT,
    scenario_id     TEXT,
    decision_id     TEXT,
    kind            TEXT NOT NULL,
    actor           TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    payload         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_tenant ON decision_journal (tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_journal_scenario ON decision_journal (scenario_id);
CREATE TABLE IF NOT EXISTS model_drift (
    drift_id    TEXT PRIMARY KEY,
    model_id    TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenario_challenges (
    challenge_id TEXT PRIMARY KEY,
    scenario_id  TEXT NOT NULL,
    tenant_id    TEXT NOT NULL DEFAULT 'default',
    created_at   TEXT NOT NULL,
    actor        TEXT NOT NULL,
    payload      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_challenge_scenario ON scenario_challenges (scenario_id);
"""

MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="initial_schema", up_sql=_INITIAL_SCHEMA, down_sql=""),
    Migration(version=2, name="closed_trades", up_sql=_CLOSED_TRADES,
              down_sql="DROP TABLE IF EXISTS closed_trades;"),
    Migration(version=3, name="supplement_governance", up_sql=_SUPPLEMENT_GOVERNANCE,
              down_sql=(
                  "DROP TABLE IF EXISTS scenario_challenges;"
                  "DROP TABLE IF EXISTS model_drift;"
                  "DROP TABLE IF EXISTS decision_journal;"
                  "DROP TABLE IF EXISTS policy_registry;"
                  "DROP TABLE IF EXISTS decision_provenance;"
              )),
)


def _ensure_meta_table(db: Database) -> None:
    """Ensure schema_migrations has a 'name' column.

    The base schema.sql declares schema_migrations with (version, applied_at).
    We add 'name' if missing. This is idempotent.
    """
    rows = db.query("PRAGMA table_info(schema_migrations)")
    if not rows:
        db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        return
    columns = {row["name"] for row in rows}
    if "name" not in columns:
        db.execute("ALTER TABLE schema_migrations ADD COLUMN name TEXT NOT NULL DEFAULT ''")


def _current_version(db: Database) -> int:
    row = db.query_one("SELECT MAX(version) AS v FROM schema_migrations")
    if row is None or row["v"] is None:
        return 0
    return int(row["v"])


def _applied_versions(db: Database) -> set[int]:
    rows = db.query("SELECT version FROM schema_migrations ORDER BY version")
    return {int(row["version"]) for row in rows}


def _record(db: Database, migration: Migration, when: datetime) -> None:
    db.execute(
        "INSERT OR REPLACE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (migration.version, migration.name, format_ts(when)),
    )


def upgrade(db: Database, *, target: int | None = None) -> dict:
    """Apply pending migrations up to `target` (default: latest)."""
    _ensure_meta_table(db)
    applied = _applied_versions(db)
    pending = [m for m in MIGRATIONS if m.version not in applied]
    if target is not None:
        pending = [m for m in pending if m.version <= target]
    pending.sort(key=lambda m: m.version)

    applied_names: list[str] = []
    for migration in pending:
        # executescript auto-commits; so don't wrap in db.transaction()
        db.executescript(migration.up_sql)
        _record(db, migration, utcnow())
        applied_names.append(migration.name)

    return {
        "applied": applied_names,
        "current_version": _current_version(db),
        "target": target,
    }


def downgrade(db: Database, *, target_version: int) -> dict:
    """Roll back to `target_version`. Reverses migrations with down_sql."""
    _ensure_meta_table(db)
    applied = _applied_versions(db)
    to_reverse = [m for m in MIGRATIONS if m.version in applied and m.version > target_version]
    to_reverse.sort(key=lambda m: m.version, reverse=True)

    reversed_names: list[str] = []
    for migration in to_reverse:
        if not migration.down_sql:
            raise RuntimeError(
                f"Migration {migration.version} ({migration.name}) has no down_sql; cannot roll back"
            )
        db.executescript(migration.down_sql)
        db.execute("DELETE FROM schema_migrations WHERE version = ?", (migration.version,))
        reversed_names.append(migration.name)

    return {
        "reversed": reversed_names,
        "current_version": _current_version(db),
        "target_version": target_version,
    }


def history(db: Database) -> list[dict]:
    """Return the applied migration history."""
    _ensure_meta_table(db)
    rows = db.query("SELECT version, name, applied_at FROM schema_migrations ORDER BY version")
    return [
        {
            "version": int(row["version"]),
            "name": row["name"],
            "applied_at": row["applied_at"],
        }
        for row in rows
    ]
