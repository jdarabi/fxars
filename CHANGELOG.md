# Changelog — FX-ARS

تمام تغییرات قابل توجه در این فایل ثبت می‌شوند.

## [v1.4.10] — 2026-11-03

### Added
- **P4-3-ext**: Postgres schema translation
  - `fxars/storage/postgres_schema.sql` (TIMESTAMPTZ, JSONB, BIGSERIAL)
  - `fxars/storage/postgres_migrations.py` (idempotent upgrade runner)
  - 5 tests (3 always run, 2 skip without psycopg/DSN)

## [v1.4.9] — 2026-11-03

### Added
- **P6-5**: Paper Trading E2E with file-based database
  - Full pipeline: Analysis → Risk → Intent → Submit → Fill → Reconciliation
  - Persistence across close/reopen
  - 3 E2E tests

### Fixed
- `ExecutionService.submit`: honor broker's actual status (UNKNOWN, REJECTED)
- `state_machine`: ACKNOWLEDGED → UNKNOWN, UNKNOWN → terminal states

## [v1.4.8] — 2026-11-03

### Added
- **P3-5**: Regime filter benchmark suite
  - `scripts/benchmark_regime.py` (baseline vs filtered, regression guard)
  - CI integration (smoke job)
  - 1 smoke test

## [v1.4.7] — 2026-11-03

### Added
- **P5-4**: Metrics dashboard HTML page
  - `/metrics-dashboard` endpoint
  - Persian RTL page with uptime, counters, gauges, histograms
  - 6 tests

## [v1.4.6] — 2026-11-03

### Added
- **P4-3**: Postgres adapter skeleton
  - `PostgresDatabase` implementing `DatabaseProtocol`
  - SQL translation (? → %s)
  - 4 tests (2 pass without psycopg)

## [v1.4.4] — 2026-11-03

### Added
- **P6-3**: Reconciliation CLI
  - `python -m fxars reconcile`
  - `python -m fxars orders list [--status ...]`
  - `python -m fxars orders show <intent_id>`
- **P6-4**: `--allowed-regimes` shortcut for `backtest` command

## [v1.4.3] — 2026-11-03

### Added
- **P6-2**: Phase Guard E2E tests
  - `make_env(phase=...)` parameter
  - 6 tests (READ_ONLY blocks, PAPER allows full pipeline)

## [v1.4.2] — 2026-11-03

### Changed
- `docs/PHASES.md`: MVP-1 complete, MVP-2 in progress
- `README.md`: regime filter results (+144% net, +182% Sharpe)

## [v1.4.1] — 2026-11-03

### Added
- **P6-1**: PaperBroker faults + Reconciliation
  - Fault injection (reject, timeout, partial)
  - `ReconciliationService` for UNKNOWN orders
  - `OrderRepository.list_intents_by_status()`
  - 9 tests

## [v1.4.0] — 2026-11-02

### Added
- **P4-2**: Migration framework (up/down/history)
- Milestone: P0-P5 complete

## [v1.3.16] — 2026-11-02

### Added
- **P4-1**: Storage Protocol
  - `DatabaseProtocol` (runtime_checkable)
  - `InMemoryDatabase` for tests
  - 5 parity tests

## [v1.3.14] — 2026-11-02

### Added
- **P5-3**: Structured logging
  - Bearer/Basic/JWT/API-key redaction
  - Error JSONL file with rotation
  - 10 tests

## [v1.3.13] — 2026-11-02

### Changed
- `docs/ALGORITHMS.md`, `docs/DECISIONS.md`: regime filter documentation

## [v1.3.12] — 2026-11-02

### Added
- **P7**: GitHub Actions CI
  - Lint (ruff), typecheck (mypy), test matrix (Ubuntu+Windows, Py3.11+3.12)
  - Coverage, smoke with regime benchmark

## [v1.3.11] — 2026-11-02

### Added
- **P3-4-ext3**: `allowed_regimes` in `BacktestSettings`

## [v1.3.10] — 2026-11-02

### Added
- **P3-4-ext2**: Regime filter in backtest
  - `BacktestConfig.allowed_regimes`
  - **Result: +144% net profit, +182% Sharpe on demo**
- 6 tests

## [v1.3.9] — 2026-11-02

### Changed
- `report.py`: consolidated calibration + regime sections

## [v1.3.7] — 2026-11-02

### Added
- **P3-4**: Regime Detection
  - `fxars/research/regime.py`: 5 regimes (TRENDING_UP/DOWN, RANGING, HIGH_VOL, LOW_VOL)
  - `regime_breakdown()` for per-regime attribution
  - 13 tests

## [v1.3.6] — 2026-11-02

### Added
- **P3-1-ext**: ML pipeline
  - `fxars/research/ml_pipeline.py`: Triple Barrier + Purged K-Fold integration
  - 7 tests

## [v1.3.5] — 2026-11-02

### Added
- **P3-1**: Triple Barrier labeling
  - `fxars/research/labeling.py`
  - 12 tests

## [v1.3.4] — 2026-11-02

### Added
- **P3-2**: Purged K-Fold
  - `fxars/research/purged_cv.py`
  - `ResearchService.run_purged_cv()`
  - 14 tests

## [v1.3.3] — 2026-11-02

### Added
- **P3-3**: Calibration
  - `fxars/research/calibration.py`: Brier, LogLoss, ECE, Temperature Scaling
  - 21 tests

## [v1.3.2] — 2026-11-02

### Added
- **P5**: Observability
  - `/api/v1/metrics` (Prometheus)
  - `/api/v1/health/live`, `/api/v1/health/ready`
  - 10 tests

## [v1.3.1] — 2026-11-02

### Added
- **P0/P1**: 10 critical fixes
  - Bitemporal invariants (Candle, EconomicEvent)
  - Session revocation on password change
  - Killswitch re-enforcement in submit
  - Idempotent replay (no duplicate audit/outbox)
  - Primary-source correlations
  - Consecutive login failures
  - Bidirectional pagination

### Fixed
- `floor_to_timeframe`: zeros microsecond (property test)
- `_Handler`: drain oversized bodies before 413

### Tests
- 188 → 338 across P0-P5

---

## Summary by milestone

| Version | Focus | Tests |
|---|---|---|
| v1.3.1 | P0/P1: Critical fixes + hardening | 188 |
| v1.3.2 | P5: Observability | 257 |
| v1.3.4 | P3-2: Purged K-Fold | 271 |
| v1.3.5 | P3-1: Triple Barrier | 283 |
| v1.3.6 | P3-1-ext: ML Pipeline | 291 |
| v1.3.7 | P3-4: Regime Detection | 303 |
| v1.3.10 | P3-4-ext2: Regime Filter | 309 |
| v1.3.12 | P7: CI Pipeline | 309 |
| v1.3.14 | P5-3: Structured Logging | 319 |
| v1.3.16 | P4-1: Storage Protocol | 324 |
| v1.4.0 | P4-2: Migration Framework | 329 |
| v1.4.1 | P6-1: PaperBroker + Reconciliation | 338 |
| v1.4.3 | P6-2: Phase Guard E2E | 344 |
| v1.4.6 | P4-3: Postgres Adapter | 348 |
| v1.4.7 | P5-4: Metrics Dashboard | 354 |
| v1.4.8 | P3-5: Regime Benchmark | 355 |
| v1.4.9 | P6-5: Paper Trading E2E | 358 |
| **v1.4.10** | **P4-3-ext: Postgres Schema** | **360** |