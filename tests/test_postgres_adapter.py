"""Postgres adapter skeleton tests (P4-3)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.storage.protocol import DatabaseProtocol

try:
    import psycopg  # noqa: F401
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False

POSTGRES_DSN = os.environ.get("FXARS_POSTGRES_DSN", "")


class _DummyProtocolCheck(unittest.TestCase):
    def test_protocol_is_runtime_checkable(self):
        from fxars.storage.db import Database
        db = Database(":memory:")
        try:
            self.assertIsInstance(db, DatabaseProtocol)
        finally:
            db.close()


@unittest.skipUnless(HAS_PSYCOPG, "psycopg not installed")
class PostgresProtocolTests(unittest.TestCase):
    def test_postgres_methods_present(self):
        from fxars.storage.postgres import PostgresDatabase
        for method in (
            "execute", "executemany", "executescript",
            "query", "query_one", "scalar",
            "transaction", "migrate", "close",
        ):
            self.assertTrue(hasattr(PostgresDatabase, method), method)

    def test_sql_translation(self):
        from fxars.storage.postgres import PostgresDatabase
        sql = "SELECT * FROM candles WHERE instrument_id = ? AND timeframe = ?"
        translated = PostgresDatabase._translate_sql(sql)
        self.assertEqual(
            translated,
            "SELECT * FROM candles WHERE instrument_id = %s AND timeframe = %s",
        )


@unittest.skipUnless(HAS_PSYCOPG, "psycopg not installed")
@unittest.skipUnless(POSTGRES_DSN, "FXARS_POSTGRES_DSN not set")
class PostgresLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fxars.storage.postgres import PostgresDatabase
        try:
            cls.db = PostgresDatabase(POSTGRES_DSN)
        except Exception as exc:
            raise unittest.SkipTest(f"cannot connect to Postgres: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_basic_query(self):
        self.db.migrate()
        row = self.db.query_one("SELECT 1 AS ok")
        self.assertIsNotNone(row)
        self.assertEqual(row["ok"], 1)


if __name__ == "__main__":
    unittest.main()
