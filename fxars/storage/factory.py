"""FIX-10-PG: factory انتخاب backend با fallback امن."""
from __future__ import annotations

import logging

from fxars.config.settings import Settings
from fxars.core.errors import ValidationError

logger = logging.getLogger("fxars.storage.factory")


def create_database(settings: Settings, *, force_backend: str | None = None,
                    allow_fallback: bool = True):
    """انتخاب backend. اگر Postgres در دسترس نبود، fallback به SQLite.

    allow_fallback=True (پیش‌فرض): در دسترس نبودن Postgres باعث fallback
    با warning می‌شود. allow_fallback=False: خطا raise می‌شود.
    """
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
        try:
            return PostgresDatabase(
                dsn,
                connect_timeout=settings.database.postgres_connect_timeout,
                statement_timeout_ms=settings.database.postgres_statement_timeout_ms,
                application_name=settings.database.postgres_application_name,
            )
        except PostgresUnavailableError as exc:
            if not allow_fallback:
                raise
            logger.warning(
                "Postgres unavailable (%s); falling back to SQLite at %s",
                exc, settings.db_path,
            )
            from fxars.storage.db import Database
            return Database(settings.db_path)

    raise ValidationError(f"db backend نامعتبر: {backend!r}")
