"""PaperBroker tests (P6-1)."""
from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.domain.enums import OrderStatus, OrderType, Phase, Side
from fxars.domain.models import OrderIntent
from fxars.execution.paper_broker import PaperBroker, PaperBrokerConfig


def _intent(
    client_order_id: str = "test-1",
    *,
    side: Side = Side.BUY,
    volume: str = "0.1",
) -> OrderIntent:
    return OrderIntent(
        intent_id=f"oi_{client_order_id}",
        client_order_id=client_order_id,
        risk_decision_id="rd_1",
        instrument_id="EURUSD",
        side=side,
        order_type=OrderType.MARKET,
        volume=Decimal(volume),
        stop_loss=Decimal("1.0800"),
        take_profit=Decimal("1.0900"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        status=OrderStatus.SUBMITTED,
        phase=Phase.PAPER,
    )


class DeterministicFillTests(unittest.TestCase):
    def test_same_order_same_fill(self):
        broker = PaperBroker()
        intent = _intent("same-1")
        order1, fills1 = broker.submit(intent, price=Decimal("1.0850"), pip_size=Decimal("0.0001"))
        order2, fills2 = broker.submit(intent, price=Decimal("1.0850"), pip_size=Decimal("0.0001"))
        self.assertEqual(order1.broker_order_id, order2.broker_order_id)
        self.assertEqual(order1.status, order2.status)

    def test_buy_fill_price_above_mid(self):
        broker = PaperBroker(PaperBrokerConfig(spread_pips=Decimal("1.0"), slippage_pips=Decimal("0")))
        intent = _intent("buy-1", side=Side.BUY)
        order, fills = broker.submit(intent, price=Decimal("1.0800"), pip_size=Decimal("0.0001"))
        self.assertAlmostEqual(float(fills[0].price), 1.08005, places=5)

    def test_sell_fill_price_below_mid(self):
        broker = PaperBroker(PaperBrokerConfig(spread_pips=Decimal("1.0"), slippage_pips=Decimal("0")))
        intent = _intent("sell-1", side=Side.SELL)
        order, fills = broker.submit(intent, price=Decimal("1.0800"), pip_size=Decimal("0.0001"))
        self.assertAlmostEqual(float(fills[0].price), 1.07995, places=5)


class FaultInjectionTests(unittest.TestCase):
    def test_reject_probability_one_always_rejects(self):
        broker = PaperBroker(PaperBrokerConfig(reject_probability=1.0))
        intent = _intent("reject-1")
        order, fills = broker.submit(intent, price=Decimal("1.0850"), pip_size=Decimal("0.0001"))
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertEqual(fills, [])

    def test_timeout_probability_one_always_unknown(self):
        broker = PaperBroker(PaperBrokerConfig(timeout_probability=1.0))
        intent = _intent("timeout-1")
        order, fills = broker.submit(intent, price=Decimal("1.0850"), pip_size=Decimal("0.0001"))
        self.assertEqual(order.status, OrderStatus.UNKNOWN)
        self.assertEqual(fills, [])

    def test_partial_fill_probability_one_partial(self):
        broker = PaperBroker(PaperBrokerConfig(
            partial_fill_probability=1.0,
            reject_probability=0.0,
            timeout_probability=0.0,
        ))
        intent = _intent("partial-1", volume="0.10")
        order, fills = broker.submit(intent, price=Decimal("1.0850"), pip_size=Decimal("0.0001"))
        self.assertEqual(order.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(fills[0].volume, Decimal("0.05"))


if __name__ == "__main__":
    unittest.main()
