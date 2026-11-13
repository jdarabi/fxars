"""اتصال SQLite، تراکنش و مهاجرت schema.

SQLite برای اجرای مستقل MVP-1 انتخاب شده است؛ قرارداد Repositoryها از پایگاه داده
جدا است تا مهاجرت به PostgreSQL بدون تغییر دامنه ممکن باشد (بخش ۱۳ سند).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fxars.core.errors import ConflictError
from fxars.core.timeutil import format_ts, utcnow
from fxars.version import SCHEMA_VERSION

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, path: str | Path = ":memory:", *, timeout: float = 30.0) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._depth = 0
        self._conn = sqlite3.connect(
            self.path,
            timeout=timeout,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 30000")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")

    # ------------------------------------------------------------------ اجرا
    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, params: Sequence[Sequence[Any]]) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.executemany(sql, params)

    def executescript(self, script: str) -> None:
        with self._lock:
            self._conn.executescript(script)

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any:
        row = self.query_one(sql, params)
        return None if row is None else row[0]

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        """تراکنش سریالی؛ فراخوانی تودرتو از همان تراکنش استفاده می‌کند."""
        with self._lock:
            if self._depth == 0:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self
            except Exception:
                self._depth -= 1
                if self._depth == 0:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self._conn.execute("COMMIT")

    # ------------------------------------------------------------------ schema
    def migrate(self) -> None:
        script = SCHEMA_PATH.read_text(encoding="utf-8")
        # executescript خودش تراکنش را COMMIT می‌کند؛ بنابراین خارج از transaction صریح اجرا می‌شود.
        with self._lock:
            self._conn.executescript(script)
            # FIX-09-OUTBOX-RETRY: افزودن ستون‌های جدید در صورت نبود
            self._ensure_column("outbox", "attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column("outbox", "last_error", "TEXT")
            self._ensure_column("outbox", "dead_letter_at", "TEXT")
            # FIX-09-IDEMPOTENCY-ATOMIC
            self._ensure_column("idempotency_keys", "state", "TEXT NOT NULL DEFAULT 'completed'")
            # FIX-14-QUARANTINE-IDEMPOTENT
            self._ensure_quarantine_idempotent()
            self._ensure_tenant_schema()
            current = self.scalar("SELECT MAX(version) FROM schema_migrations")
            if current is None:
                self.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, format_ts(utcnow())),
                )
            elif current > SCHEMA_VERSION:
                raise ConflictError(
                    f"نسخه پایگاه داده ({current}) از نسخه کد ({SCHEMA_VERSION}) جدیدتر است.",
                    details={"db_version": current, "code_version": SCHEMA_VERSION},
                )

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        cols = [row["name"] for row in self.query(f"PRAGMA table_info({table})")]
        if column not in cols:
            self.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _ensure_tenant_schema(self) -> None:
        """ستون tenant_id برای پایگاه‌های قدیمی و جدول مستاجر (مهاجرت افزایشی)."""
        self.execute(
            "CREATE TABLE IF NOT EXISTS tenants ("
            " tenant_id TEXT PRIMARY KEY, name TEXT NOT NULL,"
            " active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,"
            " plan TEXT NOT NULL DEFAULT 'basic', quota_overrides TEXT NOT NULL DEFAULT '{}')"
        )
        self._ensure_column("tenants", "plan", "TEXT NOT NULL DEFAULT 'basic'")
        self._ensure_column("tenants", "quota_overrides", "TEXT NOT NULL DEFAULT '{}'")
        self.execute(
            "INSERT OR IGNORE INTO tenants (tenant_id, name, active, created_at, plan) "
            "VALUES (?, ?, 1, ?, 'enterprise')",
            ("default", "Default Tenant", format_ts(utcnow())),
        )
        # مستاجر پیش‌فرض همان نصب شخصی اپراتور است؛ سهمیه تجاری روی آن اعمال نمی‌شود.
        self.execute(
            "UPDATE tenants SET plan='enterprise' WHERE tenant_id='default' AND plan='basic'"
        )
        for table in ("analysis_runs", "scenarios", "risk_decisions", "order_intents"):
            self._ensure_column(table, "tenant_id", "TEXT NOT NULL DEFAULT 'default'")
        self.execute(
            "CREATE INDEX IF NOT EXISTS idx_scenarios_tenant ON scenarios (tenant_id, created_at)"
        )
        self.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_intents_tenant ON order_intents (tenant_id, created_at)"
        )

    def _ensure_quarantine_idempotent(self) -> None:
        """یک ردیف قرنطینه به ازای هر کندل معیوب؛ ردیف‌های تکراری قدیمی در اولین مهاجرت ادغام می‌شوند."""
        with self.transaction():
            exists = self.scalar(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_candle_quarantine_bar'"
            )
            if exists:
                return
            self.execute(
                "DELETE FROM candle_quarantine WHERE id NOT IN ("
                "SELECT MAX(id) FROM candle_quarantine "
                "GROUP BY instrument_id, source_id, timeframe, open_time)"
            )
            self.execute(
                "CREATE UNIQUE INDEX uq_candle_quarantine_bar ON candle_quarantine "
                "(instrument_id, source_id, timeframe, open_time)"
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
