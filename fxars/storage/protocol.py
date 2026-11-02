"""Storage protocols for database-agnostic repositories.

These Protocols define the minimal interface that repositories depend on.
The current implementation uses SQLite; a future PostgreSQL adapter can
implement the same interface without touching domain/repository code.
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class DatabaseProtocol(Protocol):
    """Minimal database interface used by all repositories."""

    path: str

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any: ...

    def executemany(self, sql: str, params: Sequence[Sequence[Any]]) -> Any: ...

    def executescript(self, script: str) -> None: ...

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[Any]: ...

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any | None: ...

    def scalar(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any: ...

    def transaction(self) -> Any: ...

    def migrate(self) -> None: ...

    def close(self) -> None: ...


class InMemoryDatabase:
    """SQLite-backed in-memory database for tests."""

    def __init__(self) -> None:
        from fxars.storage.db import Database
        self._inner = Database(":memory:")
        self.path = ":memory:"

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any:
        return self._inner.execute(sql, params)

    def executemany(self, sql: str, params: Sequence[Sequence[Any]]) -> Any:
        return self._inner.executemany(sql, params)

    def executescript(self, script: str) -> None:
        self._inner.executescript(script)

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[Any]:
        return self._inner.query(sql, params)

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any | None:
        return self._inner.query_one(sql, params)

    def scalar(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any:
        return self._inner.scalar(sql, params)

    def transaction(self) -> Any:
        return self._inner.transaction()

    def migrate(self) -> None:
        self._inner.migrate()

    def close(self) -> None:
        self._inner.close()
