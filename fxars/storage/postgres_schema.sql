-- FX-ARS schema for PostgreSQL (P4-3-ext)
-- Types: TIMESTAMPTZ for time, JSONB for payload, BIGSERIAL for seq.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS instruments (
    instrument_id TEXT PRIMARY KEY,
    version       INTEGER NOT NULL,
    payload       JSONB NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS data_sources (
    source_id  TEXT PRIMARY KEY,
    payload    JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS candles (
    instrument_id  TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    timeframe      TEXT NOT NULL,
    open_time      TIMESTAMPTZ NOT NULL,
    revision       INTEGER NOT NULL,
    is_closed      BOOLEAN NOT NULL,
    quality_status TEXT NOT NULL,
    available_at   TIMESTAMPTZ NOT NULL,
    ingested_at    TIMESTAMPTZ NOT NULL,
    payload        JSONB NOT NULL,
    PRIMARY KEY (instrument_id, source_id, timeframe, open_time, revision)
);
CREATE INDEX IF NOT EXISTS idx_candles_range ON candles (instrument_id, timeframe, open_time);
CREATE INDEX IF NOT EXISTS idx_candles_available ON candles (instrument_id, timeframe, available_at);

CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id            TEXT PRIMARY KEY,
    instrument_id     TEXT NOT NULL,
    timeframe         TEXT NOT NULL,
    as_of             TIMESTAMPTZ NOT NULL,
    data_snapshot_id  TEXT NOT NULL,
    config_hash       TEXT NOT NULL,
    code_version      TEXT NOT NULL,
    model_version     TEXT NOT NULL,
    status            TEXT NOT NULL,
    correlation_id    TEXT NOT NULL,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ,
    result_hash       TEXT NOT NULL,
    evidence_count    INTEGER NOT NULL,
    decision          JSONB NOT NULL,
    data_quality      JSONB NOT NULL,
    error             TEXT
);

CREATE TABLE IF NOT EXISTS evidences (
    evidence_id    TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    module_id      TEXT NOT NULL,
    family         TEXT NOT NULL,
    observed_at    TIMESTAMPTZ NOT NULL,
    available_at   TIMESTAMPTZ NOT NULL,
    direction      TEXT NOT NULL,
    strength       DOUBLE PRECISION NOT NULL,
    payload        JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id      TEXT PRIMARY KEY,
    instrument_id    TEXT NOT NULL,
    timeframe        TEXT NOT NULL,
    direction        TEXT NOT NULL,
    status           TEXT NOT NULL,
    expiry_at        TIMESTAMPTZ NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL,
    risk_decision_id TEXT,
    analysis_run_id  TEXT NOT NULL,
    payload          JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id    TEXT PRIMARY KEY,
    scenario_id    TEXT NOT NULL,
    instrument_id  TEXT NOT NULL,
    approved       BOOLEAN NOT NULL,
    reason_code    TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL,
    valid_until    TIMESTAMPTZ NOT NULL,
    payload        JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    seq            BIGSERIAL PRIMARY KEY,
    event_id       TEXT NOT NULL UNIQUE,
    occurred_at    TIMESTAMPTZ NOT NULL,
    actor          TEXT NOT NULL,
    action         TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    payload        JSONB NOT NULL,
    prev_hash      TEXT NOT NULL,
    entry_hash     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox (
    event_id       TEXT PRIMARY KEY,
    event_type     TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    occurred_at    TIMESTAMPTZ NOT NULL,
    correlation_id TEXT NOT NULL,
    payload        JSONB NOT NULL,
    published_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS outbox_consumed (
    consumer    TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (consumer, event_id)
);

CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    role            TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    totp_secret_enc TEXT,
    active          BOOLEAN NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    tenant_id       TEXT NOT NULL,
    display_name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    ip         TEXT NOT NULL,
    revoked    BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS system_state (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    updated_by TEXT NOT NULL
);

-- Additional tables matching SQLite schema are added incrementally.
-- The full list is in schema.sql; this file covers the core for parity tests.