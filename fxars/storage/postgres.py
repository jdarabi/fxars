"""Postgres database adapter skeleton (P4-3).

This module implements DatabaseProtocol for PostgreSQL. It is a **skeleton**:
all interface methods are implemented, but schema initialization and migration
support are deferred to a future migration runner (P4-3-ext).

Note: psycopg is an optional dependency. Importing this module does not require
psycopg; only instantiating PostgresDatabase does.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Sequence


class PostgresUnavailableError(RuntimeError):
    """psycopg is not installed or the database is unreachable."""


class PostgresDatabase:
    """DatabaseProtocol implementation for PostgreSQL (skeleton)."""

    def __init__(self, dsn: str, *, timeout: float = 30.0) -> None:
        try:
            import psycopg
        except ImportError as exc:
            raise PostgresUnavailableError(
                "psycopg (v3) not installed. Install with: pip install -e .[postgres]"
            ) from exc

        self.dsn = dsn
        self.path = dsn
        import threading
        self._lock = threading.RLock()
        self._depth = 0
        self._psycopg = psycopg
        try:
            self._conn = psycopg.connect(
                dsn, autocommit=True, connect_timeout=int(timeout)
            )
        except Exception as exc:
            raise PostgresUnavailableError(
                f"Failed to connect to Postgres: {exc}"
            ) from exc

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any:
        sql = self._translate_sql(sql)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            return cur

    def executemany(self, sql: str, params: Sequence[Sequence[Any]]) -> Any:
        sql = self._translate_sql(sql)
        with self._lock:
            cur = self._conn.cursor()
            cur.executemany(sql, params)
            return cur

    def executescript(self, script: str) -> None:
        with self._lock:
            cur = self._conn.cursor()
            for statement in script.split(";"):
                statement = statement.strip()
                if statement:
                    cur.execute(statement)

    def query(
        self, sql: str, params: Sequence[Any] | dict[str, Any] = ()
    ) -> list[dict[str, Any]]:
        sql = self._translate_sql(sql)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    def query_one(
        self, sql: str, params: Sequence[Any] | dict[str, Any] = ()
    ) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return None
        return next(iter(row.values()), None)

    @contextmanager
    def transaction(self) -> Iterator["PostgresDatabase"]:
        with self._lock:
            if self._depth == 0:
                self._conn.execute("BEGIN")
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

    def migrate(self) -> None:
        """SKELETON: create minimal schema_migrations (full schema in P4-3-ext)."""
        self.executescript(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY,"
            " name TEXT NOT NULL,"
            " applied_at TIMESTAMPTZ NOT NULL"
            ");"
        )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "PostgresDatabase":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @staticmethod
    def _translate_sql(sql: str) -> str:
        """Translate SQLite '?' placeholders to psycopg '%s'."""
        return sql.replace("?", "%s")