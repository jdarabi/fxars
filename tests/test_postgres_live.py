"""FIX-10-PG: live Postgres tests (skip without psycopg + DSN)."""
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

DSN = os.environ.get("FXARS_POSTGRES_DSN", "")


@unittest.skipUnless(HAS_PSYCOPG, "psycopg not installed")
@unittest.skipUnless(DSN, "FXARS_POSTGRES_DSN not set")
class PostgresLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fxars.storage.postgres import PostgresDatabase
        cls.db = PostgresDatabase(DSN, connect_timeout=5)
        cls.db.migrate()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_health(self):
        self.assertEqual(self.db.scalar("SELECT 1 AS ok"), 1)

    def test_migrate_idempotent(self):
        from fxars.storage.postgres_migrations import upgrade_postgres
        first = upgrade_postgres(self.db)
        second = upgrade_postgres(self.db)
        self.assertEqual(second["applied"], [])
        self.assertEqual(first["current_version"], second["current_version"])

    def test_transaction_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                self.db.execute("CREATE TABLE _tmp_tx_test (k INTEGER)")
                raise RuntimeError("rollback")
        row = self.db.query_one(
            "SELECT table_name AS name FROM information_schema.tables WHERE table_name='_tmp_tx_test'"
        )
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()