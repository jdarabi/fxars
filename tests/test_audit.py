"""آزمون ممیزی، زنجیره هش و Outbox."""

from __future__ import annotations

import sqlite3
import unittest

from fxars.audit.audit import AuditAction, AuditLog
from fxars.audit.outbox import EventType, Outbox
from fxars.core.context import correlation_scope
from tests.helpers import make_env


class AuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=100)
        self.audit = self.env.platform.audit

    def tearDown(self) -> None:
        self.env.close()

    def test_chain_valid_after_appends(self) -> None:
        with correlation_scope("corr_test"):
            self.audit.append(AuditAction.USER_CREATED, "user", "u1", actor="admin")
            self.audit.append(AuditAction.DATA_INGESTED, "candle", "c1", actor="system")
        result = self.audit.verify()
        self.assertTrue(result["valid"])
        self.assertGreaterEqual(result["count"], 3)
        entries = self.audit.list_entries(limit=10)
        self.assertEqual(entries[0].correlation_id, "corr_test")

    def test_update_is_blocked(self) -> None:
        self.audit.append(AuditAction.USER_CREATED, "user", "u1", actor="admin")
        with self.assertRaises(sqlite3.DatabaseError):
            self.env.platform.db.execute("UPDATE audit_events SET actor='hacker' WHERE seq=1")

    def test_delete_is_blocked(self) -> None:
        self.audit.append(AuditAction.USER_CREATED, "user", "u1", actor="admin")
        with self.assertRaises(sqlite3.DatabaseError):
            self.env.platform.db.execute("DELETE FROM audit_events WHERE seq=1")

    def test_chain_detects_tampering(self) -> None:
        self.audit.append(AuditAction.USER_CREATED, "user", "u1", actor="admin")
        last = self.env.platform.audit_repo.last()
        self.assertIsNotNone(last)
        from fxars.core.timeutil import format_ts

        self.env.platform.db.execute(
            "INSERT INTO audit_events (event_id, occurred_at, actor, action, entity_type, entity_id, correlation_id, "
            "payload, prev_hash, entry_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("aud_forged", format_ts(last.occurred_at), "attacker", "USER_CREATED", "user", "u2", "corr",
             "{}", last.entry_hash, "0" * 64),
        )
        result = self.audit.verify()
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "entry_hash_mismatch")

    def test_two_entries_have_distinct_hashes(self) -> None:
        first = self.audit.append(AuditAction.USER_CREATED, "user", "u1")
        second = self.audit.append(AuditAction.USER_CREATED, "user", "u2")
        self.assertNotEqual(first.entry_hash, second.entry_hash)
        self.assertEqual(second.prev_hash, first.entry_hash)


class OutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=100)
        self.outbox = Outbox(self.env.platform.db)

    def tearDown(self) -> None:
        self.env.close()

    def test_emit_and_publish(self) -> None:
        event_id = self.outbox.emit(EventType.CANDLES_INGESTED, {"n": 1})
        pending = self.outbox.pending()
        self.assertGreaterEqual(len(pending), 1)
        received: list[dict] = []
        stats = self.outbox.publish_pending({
            EventType.CANDLES_INGESTED: lambda event: received.append(event),
        })
        self.assertGreaterEqual(stats["published"], 1)
        self.assertTrue(any(event["event_id"] == event_id for event in received))

    def test_consume_once_idempotent(self) -> None:
        event_id = self.outbox.emit(EventType.ANALYSIS_COMPLETED, {"run": "x"})
        calls: list[str] = []
        self.assertTrue(self.outbox.consume_once("test", event_id, lambda: calls.append("x")))
        self.assertFalse(self.outbox.consume_once("test", event_id, lambda: calls.append("x")))
        self.assertEqual(calls, ["x"])

    def test_pending_count_decreases(self) -> None:
        self.outbox.emit(EventType.ANALYSIS_COMPLETED, {"run": "x"})
        before = self.outbox.pending_count
        self.outbox.publish_pending({})
        self.assertLess(self.outbox.pending_count, before)


if __name__ == "__main__":
    unittest.main()
