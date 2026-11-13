"""آزمون endpoint پوزیشن‌های باز مانیتور لایو: منبع بروکر و fallback سوابق سیستم."""

from __future__ import annotations

import json
import unittest
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from fxars.api.server import ApiApp, ApiRequest
from fxars.domain.enums import OrderStatus, OrderType, Phase, Side
from fxars.domain.models import BrokerOrder, Fill, OrderIntent

from tests.helpers import ANALYST_PASSWORD, make_env


class _BrokerWithPositions:
    name = "test_broker"

    def __init__(self, items):
        self._items = items

    def positions(self, symbol=None):
        return list(self._items)


class _BrokenBroker:
    name = "broken_broker"

    def positions(self, symbol=None):
        raise RuntimeError("mt5 disconnected")


class LivePositionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=300, users=True)
        self.app = ApiApp(self.env.platform)
        self.counter = 0
        self.token = self.login()

    def tearDown(self) -> None:
        self.env.close()

    def call(self, method: str, path: str, body: dict | None = None,
             *, token: str | None = None) -> tuple[int, dict]:
        self.counter += 1
        parsed = urlparse(path)
        headers = {}
        if token:
            headers["authorization"] = f"Bearer {token}"
        request = ApiRequest(
            method=method, path=parsed.path, query=parse_qs(parsed.query),
            headers=headers,
            body=json.dumps(body).encode("utf-8") if body is not None else b"",
            ip="127.0.0.1",
        )
        response = self.app.handle(request)
        payload = json.loads(response.body.decode("utf-8")) if response.body else {}
        return response.status, payload

    def login(self) -> str:
        status, payload = self.call(
            "POST", "/api/v1/auth/login",
            {"username": "analyst", "password": ANALYST_PASSWORD}, token=None,
        )
        self.assertEqual(status, 200, payload)
        return payload["token"]

    def _save_open_position(
        self,
        *,
        intent_id: str = "oi_live_1",
        tenant_id: str = "default",
        status: OrderStatus = OrderStatus.FILLED,
        volume: Decimal = Decimal("0.50"),
        entry: Decimal = Decimal("1.0850"),
        with_fill: bool = True,
    ) -> OrderIntent:
        now = self.env.as_of
        intent = OrderIntent(
            intent_id=intent_id, client_order_id=f"client-{intent_id}",
            risk_decision_id="rd-live", instrument_id="EURUSD",
            side=Side.BUY, order_type=OrderType.MARKET, volume=volume,
            stop_loss=Decimal("1.0700"), take_profit=Decimal("1.1100"),
            created_at=now, status=status, phase=Phase.PAPER, tenant_id=tenant_id,
        )
        self.env.platform.orders.save_intent(intent)
        order = BrokerOrder(
            broker_order_id=f"bo-{intent_id}", intent_id=intent_id, status=status,
            symbol="EURUSD", requested_volume=volume, filled_volume=volume,
            average_price=entry, updated_at=now,
        )
        self.env.platform.orders.save_broker_order(order)
        if with_fill:
            self.env.platform.orders.save_fill(Fill(
                fill_id=f"fill-{intent_id}", broker_order_id=order.broker_order_id,
                volume=volume, price=entry, commission=Decimal("-0.35"), filled_at=now,
            ))
        return intent

    def _latest_close(self) -> Decimal:
        source_id = self.env.platform.instruments.primary_source("EURUSD", "H1")
        candle = self.env.platform.candles.latest_closed(
            "EURUSD", "H1", source_id=source_id, as_of=self.env.platform.clock(),
        )
        self.assertIsNotNone(candle)
        return candle.close

    def test_read_only_without_broker_uses_system_orders(self) -> None:
        intent = self._save_open_position()
        status, payload = self.call("GET", "/api/v1/trading/positions", token=self.token)

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["source"], "system")
        self.assertEqual(payload["phase"], "READ_ONLY")
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["count"], 1)

        position = payload["positions"][0]
        self.assertEqual(position["ticket"], intent.intent_id)
        self.assertEqual(position["side"], "BUY")
        self.assertEqual(position["status"], "FILLED")
        self.assertEqual(Decimal(position["volume"]), Decimal("0.50"))
        self.assertEqual(Decimal(position["price_open"]), Decimal("1.0850"))
        self.assertEqual(Decimal(position["commission"]), Decimal("-0.35"))

        close = self._latest_close()
        self.assertEqual(Decimal(position["price_current"]), close)
        contract_size = self.env.platform.instruments.get("EURUSD").contract_size
        expected = (close - Decimal("1.0850")) * Decimal("0.50") * contract_size
        self.assertEqual(Decimal(position["profit"]), expected)

    def test_empty_read_only_reports_system_source(self) -> None:
        status, payload = self.call("GET", "/api/v1/trading/positions", token=self.token)

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["source"], "system")
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["errors"], [])

    def test_broker_positions_take_priority(self) -> None:
        self._save_open_position()
        self.env.platform.execution.broker = _BrokerWithPositions([{
            "ticket": 555001, "symbol": "EURUSD", "type": 1,
            "volume": Decimal("0.25"), "price_open": Decimal("1.1000"),
            "price_current": Decimal("1.0950"), "profit": Decimal("12.50"),
            "commission": Decimal("-0.10"), "swap": Decimal("0"),
        }])
        status, payload = self.call("GET", "/api/v1/trading/positions", token=self.token)

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["source"], "broker")
        self.assertEqual(payload["broker"], "test_broker")
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["count"], 1)
        position = payload["positions"][0]
        self.assertEqual(position["ticket"], 555001)
        self.assertEqual(position["volume"], "0.25")
        self.assertEqual(position["price_open"], "1.1000")
        self.assertEqual(position["profit"], "12.50")

    def test_broker_failure_falls_back_without_http_error(self) -> None:
        self._save_open_position()
        self.env.platform.execution.broker = _BrokenBroker()
        status, payload = self.call("GET", "/api/v1/trading/positions", token=self.token)

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["source"], "system")
        self.assertEqual(payload["count"], 1)
        self.assertTrue(any("mt5 disconnected" in error for error in payload["errors"]))

    def test_partially_filled_intent_is_open_position(self) -> None:
        self._save_open_position(
            intent_id="oi_partial", status=OrderStatus.PARTIALLY_FILLED,
            volume=Decimal("0.20"), entry=Decimal("1.0900"), with_fill=False,
        )
        status, payload = self.call("GET", "/api/v1/trading/positions", token=self.token)

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["count"], 1)
        position = payload["positions"][0]
        self.assertEqual(position["status"], "PARTIALLY_FILLED")
        self.assertEqual(Decimal(position["volume"]), Decimal("0.20"))
        self.assertEqual(Decimal(position["price_open"]), Decimal("1.0900"))

    def test_positions_are_scoped_to_requesting_tenant(self) -> None:
        self._save_open_position(intent_id="oi_default", tenant_id="default")
        self._save_open_position(intent_id="oi_other", tenant_id="tenant_other")
        status, payload = self.call("GET", "/api/v1/trading/positions", token=self.token)

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["positions"][0]["ticket"], "oi_default")


if __name__ == "__main__":
    unittest.main()
