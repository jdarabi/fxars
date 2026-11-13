-- FX-ARS schema for PostgreSQL (FIX-10-PG)
-- Types: TIMESTAMPTZ, JSONB, BIGSERIAL.

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

CREATE TABLE IF NOT EXISTS symbol_mappings (
    source_id      TEXT NOT NULL,
    broker_symbol  TEXT NOT NULL,
    instrument_id  TEXT NOT NULL,
    valid_from     TIMESTAMPTZ NOT NULL,
    valid_to       TIMESTAMPTZ,
    payload        JSONB NOT NULL,
    PRIMARY KEY (source_id, broker_symbol, valid_from)
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

CREATE TABLE IF NOT EXISTS candle_revision_log (
    id             BIGSERIAL PRIMARY KEY,
    instrument_id  TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    timeframe      TEXT NOT NULL,
    open_time      TIMESTAMPTZ NOT NULL,
    old_revision   INTEGER NOT NULL,
    new_revision   INTEGER NOT NULL,
    old_digest     TEXT NOT NULL,
    new_digest     TEXT NOT NULL,
    reason         TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS candle_quarantine (
    id             BIGSERIAL PRIMARY KEY,
    instrument_id  TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    timeframe      TEXT NOT NULL,
    open_time      TIMESTAMPTZ NOT NULL,
    reasons        TEXT NOT NULL,
    payload        JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_payloads (
    payload_id    TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL,
    kind          TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    received_at   TIMESTAMPTZ NOT NULL,
    payload       TEXT NOT NULL,
    meta          JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS economic_events (
    event_id      TEXT NOT NULL,
    revision      INTEGER NOT NULL DEFAULT 1,
    currency      TEXT NOT NULL,
    event_time    TIMESTAMPTZ NOT NULL,
    available_at  TIMESTAMPTZ NOT NULL,
    importance    TEXT NOT NULL,
    payload       JSONB NOT NULL,
    PRIMARY KEY (event_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_events_time ON economic_events (event_time, currency);

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
    error             TEXT,
    tenant_id         TEXT NOT NULL DEFAULT 'default'
);
CREATE INDEX IF NOT EXISTS idx_analysis_instrument ON analysis_runs (instrument_id, timeframe, as_of);

CREATE TABLE IF NOT EXISTS evidences (
    evidence_id    TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    module_id      TEXT NOT NULL,
    family         TEXT NOT NULL,
    observed_at    TIMESTAMPTZ NOT NULL,
    available_at   TIMESTAMPTZ NOT NULL,
    direction      TEXT NOT NULL,
    strength       DOUBLE PRECISION NOT NULL,
    payload        JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidences_run ON evidences (run_id, family);

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
    payload          JSONB NOT NULL,
    tenant_id        TEXT NOT NULL DEFAULT 'default'
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
    occurred_at    TIMESTAMPTZ NOT NULL,
    rules_version  TEXT NOT NULL,
    data_ref       TEXT NOT NULL,
    correlation_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transitions_scenario ON scenario_transitions (scenario_id, occurred_at);

CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id    TEXT PRIMARY KEY,
    scenario_id    TEXT NOT NULL,
    instrument_id  TEXT NOT NULL,
    approved       BOOLEAN NOT NULL,
    reason_code    TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL,
    valid_until    TIMESTAMPTZ NOT NULL,
    payload        JSONB NOT NULL,
    tenant_id      TEXT NOT NULL DEFAULT 'default'
);
CREATE INDEX IF NOT EXISTS idx_risk_scenario ON risk_decisions (scenario_id, created_at);

CREATE TABLE IF NOT EXISTS data_quality_runs (
    run_id        TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    timeframe     TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    checked_at    TIMESTAMPTZ NOT NULL,
    verdict       TEXT NOT NULL,
    stale         BOOLEAN NOT NULL,
    payload       JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dq_checked ON data_quality_runs (instrument_id, checked_at);

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id           TEXT PRIMARY KEY,
    instrument_id    TEXT NOT NULL,
    timeframe        TEXT NOT NULL,
    segment          TEXT NOT NULL,
    config_hash      TEXT NOT NULL,
    data_snapshot_id TEXT NOT NULL,
    started_at       TIMESTAMPTZ NOT NULL,
    finished_at      TIMESTAMPTZ NOT NULL,
    payload          JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_backtests_started ON backtest_runs (started_at);

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
    published_at   TIMESTAMPTZ,
    attempts       INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT,
    dead_letter_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox (published_at, occurred_at);

CREATE TABLE IF NOT EXISTS outbox_consumed (
    consumer    TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (consumer, event_id)
);

CREATE TABLE IF NOT EXISTS system_state (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    updated_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL,
    plan            TEXT NOT NULL DEFAULT 'basic',
    quota_overrides TEXT NOT NULL DEFAULT '{}'
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
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, expires_at);

CREATE TABLE IF NOT EXISTS login_attempts (
    id           BIGSERIAL PRIMARY KEY,
    username     TEXT NOT NULL,
    ip           TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL,
    success      BOOLEAN NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts (username, attempted_at);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key          TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    route        TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status       INTEGER NOT NULL,
    response     JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL,
    state        TEXT NOT NULL DEFAULT 'completed',
    PRIMARY KEY (key, user_id)
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL,
    taken_at    TIMESTAMPTZ NOT NULL,
    payload     JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS order_intents (
    intent_id        TEXT PRIMARY KEY,
    client_order_id  TEXT NOT NULL UNIQUE,
    risk_decision_id TEXT NOT NULL,
    instrument_id    TEXT NOT NULL,
    status           TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    payload          JSONB NOT NULL,
    tenant_id        TEXT NOT NULL DEFAULT 'default'
);

CREATE TABLE IF NOT EXISTS broker_orders (
    broker_order_id TEXT PRIMARY KEY,
    intent_id       TEXT NOT NULL,
    status          TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL,
    payload         JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    fill_id         TEXT PRIMARY KEY,
    broker_order_id TEXT NOT NULL,
    filled_at       TIMESTAMPTZ NOT NULL,
    payload         JSONB NOT NULL
);

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

CREATE TABLE IF NOT EXISTS order_approvals (
    intent_id    TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,
    approved_by  TEXT,
    decided_at   TIMESTAMPTZ,
    reason       TEXT NOT NULL DEFAULT '',
    payload      JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS model_registry (
    model_id TEXT NOT NULL,
    version  TEXT NOT NULL,
    status   TEXT NOT NULL,
    payload  JSONB NOT NULL,
    PRIMARY KEY (model_id, version)
);

CREATE TABLE IF NOT EXISTS locked_test_access (
    access_id TEXT PRIMARY KEY,
    run_id    TEXT NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    actor     TEXT NOT NULL,
    purpose   TEXT NOT NULL
);

-- SUPPLEMENT-1.1: حاکمیت، منشأ تصمیم و قابلیت‌های محصول
CREATE TABLE IF NOT EXISTS decision_provenance (
    record_id       TEXT PRIMARY KEY,
    decision_id     TEXT NOT NULL,
    analysis_run_id TEXT NOT NULL,
    scenario_id     TEXT,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    created_at      TIMESTAMPTZ NOT NULL,
    prev_hash       TEXT NOT NULL,
    record_hash     TEXT NOT NULL,
    payload         JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provenance_run ON decision_provenance (analysis_run_id);
CREATE INDEX IF NOT EXISTS idx_provenance_decision ON decision_provenance (decision_id);

CREATE TABLE IF NOT EXISTS policy_registry (
    policy_id  TEXT NOT NULL,
    version    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    status     TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload    JSONB NOT NULL,
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
    created_at      TIMESTAMPTZ NOT NULL,
    payload         JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_tenant ON decision_journal (tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_journal_scenario ON decision_journal (scenario_id);

CREATE TABLE IF NOT EXISTS model_drift (
    drift_id    TEXT PRIMARY KEY,
    model_id    TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    payload     JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_challenges (
    challenge_id TEXT PRIMARY KEY,
    scenario_id  TEXT NOT NULL,
    tenant_id    TEXT NOT NULL DEFAULT 'default',
    created_at   TIMESTAMPTZ NOT NULL,
    actor        TEXT NOT NULL,
    payload      JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_challenge_scenario ON scenario_challenges (scenario_id);
