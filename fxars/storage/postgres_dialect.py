"""FIX-10-DIALECT: ترجمه SQL از SQLite به Postgres.

Repositoryها SQL به سبک SQLite می‌نویسند. این ماژول قبل از اجرا، SQL را
به معادل Postgres ترجمه می‌کند. اگر SQL از قبل Postgres-native باشد،
بدون تغییر عبور می‌کند.

ترجمه‌های پشتیبانی‌شده:
- ``?`` → ``%s`` (placeholder)
- ``INSERT OR REPLACE INTO t (...) VALUES (...)`` → ``INSERT ... ON CONFLICT DO UPDATE``
  (نیازمند PK/UK: در ``conflict_cols`` صریح داده می‌شود)
- ``INSERT OR IGNORE INTO`` → ``INSERT ... ON CONFLICT DO NOTHING``
- ``PRAGMA table_info(t)`` → query از information_schema
- ``last_insert_rowid()`` → ``LASTVAL()``
- ``rowid`` → نیاز به ترجمه در Repository (خارج از دامنه)

نکته: ترجمه ``INSERT OR REPLACE`` به ``ON CONFLICT DO UPDATE`` فقط وقتی
درست است که PK/UK مشخص باشد. برای Repositoryهای ما:
- users (user_id)
- sessions (token_hash)
- idempotency_keys (key, user_id)
- ...
اگر PK مشخص نیست، fallback به DELETE + INSERT.
"""
from __future__ import annotations

import re


# الگوها با regex کامپایل‌شده برای performance
_PLACEHOLDER = re.compile(r"\?")
_INSERT_OR_REPLACE = re.compile(
    r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)
_INSERT_OR_IGNORE = re.compile(
    r"INSERT\s+OR\s+IGNORE\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)
_PRAGMA_TABLE_INFO = re.compile(
    r"PRAGMA\s+table_info\(\s*(\w+)\s*\)",
    re.IGNORECASE,
)
_LAST_ROWID = re.compile(r"last_insert_rowid\s*\(\s*\)", re.IGNORECASE)


# برای ترجمه INSERT OR REPLACE، باید بدانیم PK/UK چیست
KNOWN_PK: dict[str, tuple[str, ...]] = {
    "instruments": ("instrument_id",),
    "data_sources": ("source_id",),
    "candles": ("instrument_id", "source_id", "timeframe", "open_time", "revision"),
    "analysis_runs": ("run_id",),
    "evidences": ("evidence_id",),
    "scenarios": ("scenario_id",),
    "scenario_transitions": ("transition_id",),
    "risk_decisions": ("decision_id",),
    "data_quality_runs": ("run_id",),
    "backtest_runs": ("run_id",),
    "outbox": ("event_id",),
    "system_state": ("key",),
    "users": ("user_id",),
    "sessions": ("token_hash",),
    "idempotency_keys": ("key", "user_id"),
    "account_snapshots": ("snapshot_id",),
    "order_intents": ("intent_id",),
    "broker_orders": ("broker_order_id",),
    "fills": ("fill_id",),
    "model_registry": ("model_id", "version"),
    "locked_test_access": ("access_id",),
    "raw_payloads": ("payload_id",),
    "economic_events": ("event_id", "revision"),
    "symbol_mappings": ("source_id", "broker_symbol", "valid_from"),
    "candle_revision_log": ("id",),
    "candle_quarantine": ("id",),
    "login_attempts": ("id",),
    "audit_events": ("seq",),
    "outbox_consumed": ("consumer", "event_id"),
}


def _columns_from_insert(cols_str: str) -> list[str]:
    return [c.strip().split()[0].strip('"') for c in cols_str.split(",")]


def translate(sql: str) -> str:
    """SQL با سبک SQLite را به Postgres ترجمه می‌کند."""
    # 1) PRAGMA table_info → SELECT از information_schema
    def pragma_repl(match: re.Match) -> str:
        table = match.group(1)
        return (
            f"SELECT column_name AS name FROM information_schema.columns "
            f"WHERE table_name = '{table}'"
        )
    sql = _PRAGMA_TABLE_INFO.sub(pragma_repl, sql)

    # 2) last_insert_rowid() → LASTVAL()
    sql = _LAST_ROWID.sub("LASTVAL()", sql)

    # 3) INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING
    def replace_or_ignore(match: re.Match) -> str:
        table = match.group(1)
        cols = match.group(2)
        vals = match.group(3)
        return f"INSERT INTO {table} ({cols}) VALUES ({vals}) ON CONFLICT DO NOTHING"
    sql = _INSERT_OR_IGNORE.sub(replace_or_ignore, sql)

    # 4) INSERT OR REPLACE → INSERT ... ON CONFLICT (pk) DO UPDATE SET ...
    def replace_or_replace(match: re.Match) -> str:
        table = match.group(1)
        cols_str = match.group(2)
        vals = match.group(3)
        pk = KNOWN_PK.get(table)
        if pk is None:
            # fallback: استفاده از ON CONFLICT DO UPDATE با همه ستون‌ها
            cols = _columns_from_insert(cols_str)
            update = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols)
            return f"INSERT INTO {table} ({cols_str}) VALUES ({vals}) ON CONFLICT DO UPDATE SET {update}"
        update = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols_str.split(",") if c.strip().split()[0].strip('"') not in pk)
        return (
            f"INSERT INTO {table} ({cols_str}) VALUES ({vals}) "
            f"ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {update}"
        )
    sql = _INSERT_OR_REPLACE.sub(replace_or_replace, sql)

    # 5) ? → %s
    sql = _PLACEHOLDER.sub("%s", sql)

    return sql
