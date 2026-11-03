"""FIX-10-PG: factory برای انتخاب backend پایگاه داده.

قواعد:
* backend = "sqlite" (پیش‌فرض) → SQLite
* backend = "postgres" → PostgreSQL (نیازمند psycopg + DSN)
* در محیط prod اگر backend=postgres و DSN خالی باشد، fail-fast.
"""
from __future__ import annotations

from fxars.config.settings import Settings
from fxars.core.errors import ValidationError


def create_database(settings: Settings, *, force_backend: str | None = None):
    backend = (force_backend or settings.database.backend or "sqlite").lower()
    if backend == "sqlite":
        from fxars.storage.db import Database
        return Database(settings.db_path)
    if backend == "postgres":
        from fxars.storage.postgres import PostgresDatabase, PostgresUnavailableError
        dsn = settings.database.postgres_dsn
        if not dsn:
            raise ValidationError(
                "backend=postgres اما postgres_dsn تنظیم نشده است.",
                details={"hint": "FXARS_POSTGRES_DSN یا settings.database.postgres_dsn"},
            )
        return PostgresDatabase(
            dsn,
            connect_timeout=settings.database.postgres_connect_timeout,
            statement_timeout_ms=settings.database.postgres_statement_timeout_ms,
            application_name=settings.database.postgres_application_name,
        )
    raise ValidationError(f"db backend نامعتبر: {backend!r}")