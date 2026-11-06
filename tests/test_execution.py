"""آزمون لایه اجرا: مسدود بودن در MVP-1 و ماشین حالت سفارش."""

from __future__ import annotations

import unittest

from fxars.core.errors import ConflictError, PhaseViolationError
from fxars.domain.enums import OrderStatus, Phase, Side
from fxars.domain.models import OrderIntent
from fxars.execution.paper_broker import PaperBroker
from fxars.execution.state_machine import can_transition, transition

from tests.helpers import make_env


class PhaseGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)

    def tearDown(self) -> None:
        self.env.close()

    def test_readonly_blocks_order_intent(self) -> None:
        with self.assertRaises(PhaseViolationError):
            self.env.platform.execution.create_intent("sc_missing")

    def test_audit_records_blocked_attempt(self) -> None:
        with self.assertRaises(PhaseViolationError):
            self.env.platform.execution.create_intent("sc_test", actor="analyst")
        actions = [entry.action for entry in self.env.platform.audit.list_entries(limit=20)]
        self.assertIn("ORDER_INTENT_BLOCKED", actions)

    def test_settings_phase(self) -> None:
        self.assertEqual(self.env.settings.phase, Phase.READ_ONLY)
        self.assertFalse(self.env.settings.execution_enabled)


class OrderStateMachineTests(unittest.TestCase):
    def test_allowed_transitions(self) -> None:
        self.assertTrue(can_transition(OrderStatus.INTENT_CREATED, OrderStatus.RISK_APPROVED))
        self.assertTrue(can_transition(OrderStatus.RISK_APPROVED, OrderStatus.SUBMITTED))
        self.assertTrue(can_transition(OrderStatus.SUBMITTED, OrderStatus.ACKNOWLEDGED))
        self.assertTrue(can_transition(OrderStatus.ACKNOWLEDGED, OrderStatus.FILLED))
        self.assertFalse(can_transition(OrderStatus.FILLED, OrderStatus.SUBMITTED))
        self.assertFalse(can_transition(OrderStatus.CANCELED, OrderStatus.FILLED))

    def intent(self) -> OrderIntent:
        return OrderIntent(
            intent_id="oi_1", client_order_id="client-1", risk_decision_id="rd_1", instrument_id="EURUSD",
            side=Side.BUY, order_type="MARKET", volume="0.1", stop_loss="1.0800", take_profit="1.0900",
            created_at="2026-10-30T10:00:00Z", status=OrderStatus.INTENT_CREATED, phase=Phase.PAPER,
        )

    def test_transition(self) -> None:
        intent = transition(self.intent(), OrderStatus.RISK_APPROVED)
        self.assertEqual(intent.status, OrderStatus.RISK_APPROVED)
        with self.assertRaises(ConflictError):
            transition(intent, OrderStatus.FILLED)

    def test_paper_broker_deterministic(self) -> None:
        broker = PaperBroker()
        intent = transition(self.intent(), OrderStatus.RISK_APPROVED)
        first_order, first_fills = broker.submit(intent, price=__import__("decimal").Decimal("1.0850"),
                                                 pip_size=__import__("decimal").Decimal("0.0001"))
        second_order, second_fills = broker.submit(intent, price=__import__("decimal").Decimal("1.0850"),
                                                   pip_size=__import__("decimal").Decimal("0.0001"))
        self.assertEqual(first_order.broker_order_id, second_order.broker_order_id)
        self.assertEqual(first_fills[0].price, second_fills[0].price)
        self.assertEqual(first_order.requested_volume, intent.volume)


if __name__ == "__main__":
    unittest.main()
