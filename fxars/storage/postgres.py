"""FIX-10-PG: PostgresDatabase کامل — MVP-2 infrastructure.

ویژگی‌ها:
* autocommit=True برای اجرای تک‌دستور (مثل SQLite)
* transaction() با BEGIN + SAVEPOINT برای تودرتو
* row_factory=dict_row → دسترسی با row["col"]
* _translate_sql از postgres_dialect (پلیس‌هولدر، INSERT OR REPLACE/IGNORE، PRAGMA، LASTVAL)
* migrate() → upgrade_postgres (schema_migrations جدول‌ها)
"""
from __future__ import annotations

import re
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from fxars.storage.postgres_dialect import translate as _translate_dialect


class PostgresUnavailableError(RuntimeError):
    """psycopg نصب نیست یا اتصال ممکن نیست."""


_COMMENT_RE = re.compile(r"--[^\n]*")


class PostgresDatabase:
    """DatabaseProtocol implementation for PostgreSQL."""

    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout: int = 10,
        statement_timeout_ms: int = 30000,
        application_name: str = "fxars",
    ) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise PostgresUnavailableError(
                "psycopg (v3) not installed. Install with: pip install -e .[postgres]"
            ) from exc

        self.dsn = dsn
        self.path = dsn
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._lock = threading.RLock()
        self._depth = 0
        try:
            self._conn = psycopg.connect(
                dsn,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=connect_timeout,
                application_name=application_name,
            )
        except Exception as exc:
            raise PostgresUnavailableError(f"failed to connect to Postgres: {exc}") from exc
        # statement_timeout per session
        try:
            self._conn.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
        except Exception:
            pass

    # ---------------------------------------------------------------- execute
    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any:
        sql = _translate_dialect(sql)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            return cur

    def executemany(self, sql: str, params: Sequence[Sequence[Any]]) -> Any:
        sql = _translate_dialect(sql)
        with self._lock:
            cur = self._conn.cursor()
            cur.executemany(sql, params)
            return cur

    def executescript(self, script: str) -> None:
        script = _COMMENT_RE.sub("", script)
        statements = [s.strip() for s in script.split(";") if s.strip()]
        with self._lock:
            own_tx = self._depth == 0
            if own_tx:
                self._conn.execute("BEGIN")
            try:
                cur = self._conn.cursor()
                for stmt in statements:
                    cur.execute(stmt)
                if own_tx:
                    self._conn.execute("COMMIT")
            except Exception:
                if own_tx:
                    self._conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[dict[str, Any]]:
        sql = _translate_dialect(sql)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            return list(cur.fetchall())

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
        sql = _translate_dialect(sql)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            return cur.fetchone()

    def scalar(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return None
        return next(iter(row.values()), None)

    @contextmanager
    def transaction(self) -> Iterator[PostgresDatabase]:
        with self._lock:
            if self._depth == 0:
                self._conn.execute("BEGIN")
            else:
                self._conn.execute(f"SAVEPOINT sp_{self._depth}")
            self._depth += 1
            try:
                yield self
            except Exception:
                self._depth -= 1
                if self._depth == 0:
                    self._conn.execute("ROLLBACK")
                else:
                    self._conn.execute(f"ROLLBACK TO SAVEPOINT sp_{self._depth}")
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self._conn.execute("COMMIT")
                else:
                    self._conn.execute(f"RELEASE SAVEPOINT sp_{self._depth}")

    def migrate(self) -> None:
        from fxars.storage.postgres_migrations import upgrade_postgres
        upgrade_postgres(self)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> PostgresDatabase:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @staticmethod
    def _translate_sql(sql: str) -> str:
        """سازگاری با نسخه قدیمی (تست‌ها)."""
        return _translate_dialect(sql)


# alias برای سازگاری
translate = PostgresDatabase._translate_sql
