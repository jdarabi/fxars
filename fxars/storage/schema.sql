-- FX-ARS schema v1 (SQLite)
-- قواعد: JSON payload برای موجودیت‌ها + ستون‌های ایندکس‌پذیر؛ Audit و Raw فقط append-only.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

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

CREATE TABLE IF NOT EXISTS symbol_mappings (
    source_id      TEXT NOT NULL,
    broker_symbol  TEXT NOT NULL,
    instrument_id  TEXT NOT NULL,
    valid_from     TEXT NOT NULL,
    valid_to       TEXT,
    payload        TEXT NOT NULL,
    PRIMARY KEY (source_id, broker_symbol, valid_from)
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

CREATE TABLE IF NOT EXISTS candle_revision_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id  TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    timeframe      TEXT NOT NULL,
    open_time      TEXT NOT NULL,
    old_revision   INTEGER NOT NULL,
    new_revision   INTEGER NOT NULL,
    old_digest     TEXT NOT NULL,
    new_digest     TEXT NOT NULL,
    reason         TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candle_quarantine (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id  TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    timeframe      TEXT NOT NULL,
    open_time      TEXT NOT NULL,
    reasons        TEXT NOT NULL,
    payload        TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_payloads (
    payload_id    TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL,
    kind          TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    received_at   TEXT NOT NULL,
    payload       TEXT NOT NULL,
    meta          TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS raw_payloads_no_update BEFORE UPDATE ON raw_payloads
BEGIN SELECT RAISE(ABORT, 'raw_payloads is append-only'); END;
CREATE TRIGGER IF NOT EXISTS raw_payloads_no_delete BEFORE DELETE ON raw_payloads
BEGIN SELECT RAISE(ABORT, 'raw_payloads is append-only'); END;

CREATE TABLE IF NOT EXISTS economic_events (
    event_id      TEXT NOT NULL,
    revision      INTEGER NOT NULL DEFAULT 1,
    currency      TEXT NOT NULL,
    event_time    TEXT NOT NULL,
    available_at  TEXT NOT NULL,
    importance    TEXT NOT NULL,
    payload       TEXT NOT NULL,
    PRIMARY KEY (event_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_events_time ON economic_events (event_time, currency);

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
CREATE INDEX IF NOT EXISTS idx_analysis_instrument ON analysis_runs (instrument_id, timeframe, as_of);

CREATE TABLE IF NOT EXISTS evidences (
    evidence_id    TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    module_id      TEXT NOT NULL,
    family         TEXT NOT NULL,
    observed_at    TEXT NOT NULL,
    available_at   TEXT NOT NULL,
    direction      TEXT NOT NULL,
    strength       REAL NOT NULL,
    payload        TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES analysis_runs (run_id)
);
CREATE INDEX IF NOT EXISTS idx_evidences_run ON evidences (run_id, family);

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
CREATE INDEX IF NOT EXISTS idx_scenarios_status ON scenarios (status, instrument_id);

CREATE TABLE IF NOT EXISTS scenario_transitions (
    transition_id  TEXT PRIMARY KEY,
    scenario_id    TEXT NOT NULL,
    from_status    TEXT NOT NULL,
    to_status      TEXT NOT NULL,
    event          TEXT NOT NULL,
    actor          TEXT NOT NULL,
    reason         TEXT NOT NULL,
    occurred_at    TEXT NOT NULL,
    rules_version  TEXT NOT NULL,
    data_ref       TEXT NOT NULL,
    correlation_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transitions_scenario ON scenario_transitions (scenario_id, occurred_at);

CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id   TEXT PRIMARY KEY,
    scenario_id   TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    approved      INTEGER NOT NULL,
    reason_code   TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    valid_until   TEXT NOT NULL,
    payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_risk_scenario ON risk_decisions (scenario_id, created_at);

CREATE TABLE IF NOT EXISTS data_quality_runs (
    run_id        TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    timeframe     TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    checked_at    TEXT NOT NULL,
    verdict       TEXT NOT NULL,
    stale         INTEGER NOT NULL,
    payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dq_checked ON data_quality_runs (instrument_id, checked_at);

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id           TEXT PRIMARY KEY,
    instrument_id    TEXT NOT NULL,
    timeframe        TEXT NOT NULL,
    segment          TEXT NOT NULL,
    config_hash      TEXT NOT NULL,
    data_snapshot_id TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    finished_at      TEXT NOT NULL,
    payload          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_backtests_started ON backtest_runs (started_at);

CREATE TABLE IF NOT EXISTS audit_events (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT NOT NULL UNIQUE,
    occurred_at    TEXT NOT NULL,
    actor          TEXT NOT NULL,
    action         TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    payload        TEXT NOT NULL,
    prev_hash      TEXT NOT NULL,
    entry_hash     TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

CREATE TABLE IF NOT EXISTS outbox (
    event_id       TEXT PRIMARY KEY,
    event_type     TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    occurred_at    TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    payload        TEXT NOT NULL,
    published_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox (published_at, occurred_at);

CREATE TABLE IF NOT EXISTS outbox_consumed (
    consumer    TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    consumed_at TEXT NOT NULL,
    PRIMARY KEY (consumer, event_id)
);

CREATE TABLE IF NOT EXISTS system_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    role            TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    totp_secret_enc TEXT,
    active          INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    display_name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip         TEXT NOT NULL,
    revoked    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, expires_at);

CREATE TABLE IF NOT EXISTS login_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT NOT NULL,
    ip           TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    success      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts (username, attempted_at);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key          TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    route        TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status       INTEGER NOT NULL,
    response     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (key, user_id)
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL,
    taken_at    TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_intents (
    intent_id         TEXT PRIMARY KEY,
    client_order_id   TEXT NOT NULL UNIQUE,
    risk_decision_id  TEXT NOT NULL,
    instrument_id     TEXT NOT NULL,
    status            TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    payload           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broker_orders (
    broker_order_id TEXT PRIMARY KEY,
    intent_id       TEXT NOT NULL,
    status          TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    payload         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    fill_id         TEXT PRIMARY KEY,
    broker_order_id TEXT NOT NULL,
    filled_at       TEXT NOT NULL,
    payload         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_registry (
    model_id TEXT NOT NULL,
    version  TEXT NOT NULL,
    status   TEXT NOT NULL,
    payload  TEXT NOT NULL,
    PRIMARY KEY (model_id, version)
);

CREATE TABLE IF NOT EXISTS locked_test_access (
    access_id  TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL,
    opened_at  TEXT NOT NULL,
    actor      TEXT NOT NULL,
    purpose    TEXT NOT NULL
);
