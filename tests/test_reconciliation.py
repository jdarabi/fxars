"""Reconciliation tests (P6-1)."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.audit.audit import AuditLog
from fxars.audit.outbox import Outbox
from fxars.domain.enums import OrderStatus, OrderType, Phase, Side
from fxars.domain.models import OrderIntent
from fxars.execution.reconciliation import ReconciliationService
from fxars.storage.db import Database
from fxars.storage.repositories import OrderRepository


class _NullBroker:
    def query(self, client_order_id: str):
        return None


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.db.migrate()
        self.orders = OrderRepository(self.db)
        self.audit = AuditLog(self.db)
        self.outbox = Outbox(self.db)
        self.now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.db.close()

    def _save_unknown(self, client_order_id: str) -> OrderIntent:
        intent = OrderIntent(
            intent_id=f"oi_{client_order_id}",
            client_order_id=client_order_id,
            risk_decision_id="rd_1",
            instrument_id="EURUSD",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            volume=Decimal("0.10"),
            stop_loss=Decimal("1.0800"),
            take_profit=Decimal("1.0900"),
            created_at=self.now,
            status=OrderStatus.UNKNOWN,
            phase=Phase.PAPER,
        )
        self.orders.save_intent(intent)
        return intent

    def test_broker_no_record_goes_reconciliation_required(self):
        intent = self._save_unknown("unknown-1")
        svc = ReconciliationService(
            orders=self.orders, broker=_NullBroker(),
            audit=self.audit, outbox=self.outbox, clock=lambda: self.now,
        )
        results = svc.reconcile_all()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].to_status, OrderStatus.RECONCILIATION_REQUIRED)
        reloaded = self.orders.get_intent(intent.intent_id)
        self.assertEqual(reloaded.status, OrderStatus.RECONCILIATION_REQUIRED)

    def test_no_unknown_no_action(self):
        svc = ReconciliationService(
            orders=self.orders, broker=_NullBroker(),
            audit=self.audit, outbox=self.outbox, clock=lambda: self.now,
        )
        self.assertEqual(svc.reconcile_all(), [])

    def test_audit_recorded(self):
        self._save_unknown("audit-1")
        svc = ReconciliationService(
            orders=self.orders, broker=_NullBroker(),
            audit=self.audit, outbox=self.outbox, clock=lambda: self.now,
        )
        svc.reconcile_all()
        entries = self.audit.list_entries(limit=100)
        actions = [e.action for e in entries]
        self.assertIn("RECONCILIATION_REQUIRED", actions)


if __name__ == "__main__":
    unittest.main()