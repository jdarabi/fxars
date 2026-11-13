"""آزمون storage factory (FIX-COVERAGE-FACTORY)."""
from __future__ import annotations

import unittest

from fxars.config.settings import Settings
from fxars.core.errors import ValidationError
from fxars.storage.db import Database
from fxars.storage.factory import create_database


class StorageFactoryTests(unittest.TestCase):
    def test_sqlite_backend_default(self):
        settings = Settings.from_dict({"db_path": ":memory:"})
        db = create_database(settings)
        try:
            self.assertIsInstance(db, Database)
            self.assertEqual(db.path, ":memory:")
        finally:
            db.close()

    def test_sqlite_explicit(self):
        settings = Settings.from_dict({
            "db_path": ":memory:",
            "database": {"backend": "sqlite"},
        })
        db = create_database(settings)
        try:
            self.assertIsInstance(db, Database)
        finally:
            db.close()

    def test_postgres_without_dsn_raises(self):
        settings = Settings.from_dict({
            "db_path": ":memory:",
            "database": {"backend": "postgres", "postgres_dsn": ""},
        })
        with self.assertRaises(ValidationError) as ctx:
            create_database(settings)
        self.assertIn("postgres_dsn", str(ctx.exception))

    def test_postgres_fallback_to_sqlite_when_unavailable(self):
        settings = Settings.from_dict({
            "db_path": ":memory:",
            "database": {
                "backend": "postgres",
                "postgres_dsn": "postgresql://nonexistent:5432/db",
                "postgres_connect_timeout": 1,
            },
        })
        # psycopg نصب نیست یا اتصال ممکن نیست → fallback به SQLite
        db = create_database(settings, allow_fallback=True)
        try:
            self.assertIsInstance(db, Database)
        finally:
            db.close()

    def test_postgres_strict_raises_without_fallback(self):
        from fxars.storage.postgres import PostgresUnavailableError
        settings = Settings.from_dict({
            "db_path": ":memory:",
            "database": {
                "backend": "postgres",
                "postgres_dsn": "postgresql://nonexistent:5432/db",
                "postgres_connect_timeout": 1,
            },
        })
        with self.assertRaises((PostgresUnavailableError, ValidationError, Exception)):
            create_database(settings, allow_fallback=False)

    def test_unknown_backend_raises(self):
        settings = Settings.from_dict({
            "db_path": ":memory:",
            "database": {"backend": "oracle"},
        })
        with self.assertRaises(ValidationError) as ctx:
            create_database(settings)
        self.assertIn("backend", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
