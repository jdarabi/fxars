"""Postgres schema tests (P4-3-ext).

Tests run only if:
- psycopg is installed
- FXARS_POSTGRES_DSN is set

Otherwise they are skipped.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import psycopg  # noqa: F401
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False

POSTGRES_DSN = os.environ.get("FXARS_POSTGRES_DSN", "")


class SchemaFileTests(unittest.TestCase):
    def test_schema_file_exists(self):
        path = _ROOT / "fxars" / "storage" / "postgres_schema.sql"
        self.assertTrue(path.exists())
        content = path.read_text(encoding="utf-8")
        self.assertIn("TIMESTAMPTZ", content)
        self.assertIn("JSONB", content)
        self.assertIn("BIGSERIAL", content)
        self.assertIn("CREATE TABLE IF NOT EXISTS instruments", content)

    def test_migration_module_imports(self):
        from fxars.storage.postgres_migrations import (
            PostgresMigration,
            load_initial_migration,
            upgrade_postgres,
        )
        self.assertIsNotNone(PostgresMigration)
        self.assertIsNotNone(load_initial_migration)
        self.assertIsNotNone(upgrade_postgres)

    def test_load_initial_migration(self):
        from fxars.storage.postgres_migrations import load_initial_migration
        migration = load_initial_migration()
        self.assertEqual(migration.version, 1)
        self.assertIn("instruments", migration.up_sql)


@unittest.skipUnless(HAS_PSYCOPG, "psycopg not installed")
@unittest.skipUnless(POSTGRES_DSN, "FXARS_POSTGRES_DSN not set")
class PostgresLiveSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fxars.storage.postgres import PostgresDatabase
        try:
            cls.db = PostgresDatabase(POSTGRES_DSN)
        except Exception as exc:
            raise unittest.SkipTest(f"cannot connect: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_upgrade_creates_tables(self):
        from fxars.storage.postgres_migrations import upgrade_postgres
        result = upgrade_postgres(self.db)
        self.assertGreaterEqual(result["current_version"], 1)
        # Verify core tables exist
        for table in ("instruments", "candles", "analysis_runs", "audit_events"):
            row = self.db.query_one(
                "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
                (table,),
            )
            self.assertIsNotNone(row, f"table {table} should exist")

    def test_migration_idempotent(self):
        from fxars.storage.postgres_migrations import upgrade_postgres
        first = upgrade_postgres(self.db)
        second = upgrade_postgres(self.db)
        self.assertEqual(second["applied"], [])
        self.assertEqual(first["current_version"], second["current_version"])


if __name__ == "__main__":
    unittest.main()
