"""Migration framework tests (P4-2)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.storage.db import Database
from fxars.storage.migrations import (
    MIGRATIONS,
    downgrade,
    history,
    upgrade,
)


def _fresh_db() -> Database:
    db = Database(":memory:")
    db.executescript(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL);"
    )
    return db


class MigrationTests(unittest.TestCase):
    def test_fresh_database_starts_at_zero(self):
        db = _fresh_db()
        try:
            h = history(db)
            self.assertIsInstance(h, list)
            self.assertEqual(h, [])
        finally:
            db.close()

    def test_upgrade_applies_all_pending(self):
        db = _fresh_db()
        try:
            result = upgrade(db)
            self.assertIn("initial_schema", result["applied"])
            self.assertGreaterEqual(result["current_version"], 1)
            h = history(db)
            self.assertTrue(any(item["name"] == "initial_schema" for item in h))
        finally:
            db.close()

    def test_upgrade_idempotent(self):
        db = _fresh_db()
        try:
            first = upgrade(db)
            second = upgrade(db)
            self.assertGreaterEqual(len(first["applied"]), 1)
            self.assertEqual(second["applied"], [])
        finally:
            db.close()

    def test_downgrade_requires_down_sql(self):
        db = _fresh_db()
        try:
            upgrade(db)
            with self.assertRaises(RuntimeError):
                downgrade(db, target_version=0)
        finally:
            db.close()

    def test_migrations_are_ordered(self):
        versions = [m.version for m in MIGRATIONS]
        self.assertEqual(versions, sorted(versions))
        self.assertEqual(len(versions), len(set(versions)))


if __name__ == "__main__":
    unittest.main()