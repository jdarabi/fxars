"""FIX-10-PG: PostgreSQL migration runner.

منبع حقیقت: postgres_schema.sql (idempotent).
upgrade_postgres(db) → CREATE TABLE IF NOT EXISTS ... + INSERT schema_migrations.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fxars.core.timeutil import format_ts, utcnow

SCHEMA_PATH = Path(__file__).with_name("postgres_schema.sql")

_QUARANTINE_IDEMPOTENT = """
DELETE FROM candle_quarantine WHERE id NOT IN (
    SELECT MAX(id) FROM candle_quarantine
    GROUP BY instrument_id, source_id, timeframe, open_time
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_candle_quarantine_bar
    ON candle_quarantine (instrument_id, source_id, timeframe, open_time);
"""


_TENANT_ISOLATION = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL
);
INSERT INTO tenants (tenant_id, name, active, created_at)
VALUES ('default', 'Default Tenant', TRUE, NOW()) ON CONFLICT (tenant_id) DO NOTHING;
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE risk_decisions ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE order_intents ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS idx_scenarios_tenant ON scenarios (tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_order_intents_tenant ON order_intents (tenant_id, created_at);
"""


_TENANT_PLANS = """
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'basic';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS quota_overrides TEXT NOT NULL DEFAULT '{}';
UPDATE tenants SET plan = 'enterprise' WHERE tenant_id = 'default' AND plan = 'basic';
"""


_CLOSED_TRADES = """
CREATE TABLE IF NOT EXISTS closed_trades (
    trade_id      TEXT PRIMARY KEY,
    intent_id     TEXT NOT NULL UNIQUE,
    tenant_id     TEXT NOT NULL DEFAULT 'default',
    instrument_id TEXT NOT NULL,
    side          TEXT NOT NULL,
    scenario_id   TEXT,
    closed_at     TIMESTAMPTZ NOT NULL,
    volume        TEXT NOT NULL,
    net_profit    TEXT NOT NULL,
    payload       JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_closed_trades_tenant ON closed_trades (tenant_id, closed_at);
CREATE INDEX IF NOT EXISTS idx_closed_trades_instrument ON closed_trades (instrument_id, closed_at);
"""


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


def load_migrations() -> list[PostgresMigration]:
    return [
        load_initial_migration(),
        PostgresMigration(
            version=2, name="candle_quarantine_idempotent", up_sql=_QUARANTINE_IDEMPOTENT,
        ),
        PostgresMigration(
            version=3, name="tenant_isolation", up_sql=_TENANT_ISOLATION,
        ),
        PostgresMigration(
            version=4, name="tenant_plans", up_sql=_TENANT_PLANS,
        ),
        PostgresMigration(
            version=5, name="closed_trades", up_sql=_CLOSED_TRADES,
        ),
    ]


def _ensure_meta_table(db) -> None:
    db.executescript(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " applied_at TIMESTAMPTZ NOT NULL)"
    )


def upgrade_postgres(db, *, target: int | None = None) -> dict:
    _ensure_meta_table(db)
    migrations = load_migrations()
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
