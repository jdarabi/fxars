"""Unit tests for MT5Broker using a mocked MetaTrader5 module.

این تست‌ها به نصب بودن MetaTrader5 یا اتصال به broker نیاز ندارند.
تمام تعامل با mt5.* شبیه‌سازی شده است.
"""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path as _P
from unittest.mock import MagicMock

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.domain.enums import OrderStatus, OrderType, Phase, Side
from fxars.domain.models import OrderIntent


def _make_intent(
    client_order_id: str = "test-1",
    *,
    side: Side = Side.BUY,
    volume: str = "0.10",
    instrument_id: str = "EURUSD",
) -> OrderIntent:
    return OrderIntent(
        intent_id=f"oi_{client_order_id}",
        client_order_id=client_order_id,
        risk_decision_id="rd_1",
        instrument_id=instrument_id,
        side=side,
        order_type=OrderType.MARKET,
        volume=Decimal(volume),
        stop_loss=Decimal("1.08000"),
        take_profit=Decimal("1.09000"),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        status=OrderStatus.SUBMITTED,
        phase=Phase.DEMO,
    )


def _install_fake_mt5(*, is_demo: bool = True, has_account: bool = True) -> types.ModuleType:
    """Create a fake MetaTrader5 module and register it in sys.modules."""
    fake = types.ModuleType("MetaTrader5")

    # --- state ---
    state = {
        "initialized": False,
        "shutdown_called": False,
        "last_error": (0, "ok"),
        "account": None,
        "symbol": None,
        "tick": None,
        "order_result": None,
    }

    # --- constants (match MT5 SDK) ---
    fake.TIMEFRAME_M1 = 1
    fake.TIMEFRAME_M5 = 5
    fake.TIMEFRAME_M15 = 15
    fake.TIMEFRAME_M30 = 30
    fake.TIMEFRAME_H1 = 16385
    fake.TIMEFRAME_H4 = 16388
    fake.TIMEFRAME_D1 = 16408
    fake.TIMEFRAME_W1 = 32769

    fake.ORDER_TYPE_BUY = 0
    fake.ORDER_TYPE_SELL = 1

    fake.ORDER_FILLING_FOK = 0
    fake.ORDER_FILLING_IOC = 1
    fake.ORDER_FILLING_RETURN = 2

    fake.ORDER_TIME_GTC = 0

    fake.TRADE_ACTION_DEAL = 1
    fake.TRADE_ACTION_SLTP = 6

    fake.TRADE_RETCODE_DONE = 10009
    fake.TRADE_RETCODE_REQUOTE = 10004
    fake.TRADE_RETCODE_REJECT = 10006
    fake.TRADE_RETCODE_INVALID_VOLUME = 10014
    fake.TRADE_RETCODE_MARKET_CLOSED = 10018

    # --- helpers to configure ---
    def set_account(login, server, balance, trade_mode=0):
        state["account"] = types.SimpleNamespace(
            login=login, server=server, balance=balance,
            equity=balance, margin_free=balance,
            currency="USD", leverage=100,
            trade_mode=trade_mode,
        )

    def set_symbol(
        name="EURUSD", *, visible=True, volume_min=0.01, volume_max=100.0,
        volume_step=0.01, digits=5, point=0.00001, spread=10,
        trade_contract_size=100000.0,
        currency_base="EUR", currency_profit="USD",
    ):
        state["symbol"] = types.SimpleNamespace(
            name=name, visible=visible,
            volume_min=volume_min, volume_max=volume_max, volume_step=volume_step,
            digits=digits, point=point, spread=spread,
            trade_contract_size=trade_contract_size,
            currency_base=currency_base, currency_profit=currency_profit,
        )

    def set_tick(*, ask=1.09000, bid=1.08990):
        state["tick"] = types.SimpleNamespace(ask=ask, bid=bid)

    def set_order_result(*, retcode=10009, volume=0.10, price=1.09000, order=1234567, comment=""):
        state["order_result"] = types.SimpleNamespace(
            retcode=retcode, volume=volume, price=price,
            order=order, comment=comment,
        )

    fake._set_account = set_account
    fake._set_symbol = set_symbol
    fake._set_tick = set_tick
    fake._set_order_result = set_order_result
    fake._state = state

    # --- API ---
    def initialize():
        state["initialized"] = True
        return True

    def shutdown():
        state["shutdown_called"] = True
        return True

    def last_error():
        return state["last_error"]

    def account_info():
        return state["account"]

    def symbol_info(name):
        if state["symbol"] is None:
            return None
        if state["symbol"].name != name:
            return None
        return state["symbol"]

    def symbol_select(name, enable):
        return True

    def symbol_info_tick(name):
        return state["tick"]

    def order_send(request):
        state["last_order_request"] = request
        return state["order_result"]

    fake.initialize = initialize
    fake.shutdown = shutdown
    fake.last_error = last_error
    fake.account_info = account_info
    fake.symbol_info = symbol_info
    fake.symbol_select = symbol_select
    fake.symbol_info_tick = symbol_info_tick
    fake.order_send = order_send

    return fake


class _MT5BrokerTestBase(unittest.TestCase):
    """نصب fake mt5 در sys.modules قبل از هر تست، پاک‌سازی بعد از آن."""

    def setUp(self):
        # save any real mt5
        self._real_mt5 = sys.modules.pop("MetaTrader5", None)
        self._real_broker_mod = sys.modules.pop("fxars.execution.mt5_broker", None)
        self.fake = _install_fake_mt5()
        sys.modules["MetaTrader5"] = self.fake

    def tearDown(self):
        sys.modules.pop("MetaTrader5", None)
        sys.modules.pop("fxars.execution.mt5_broker", None)
        if self._real_mt5 is not None:
            sys.modules["MetaTrader5"] = self._real_mt5
        if self._real_broker_mod is not None:
            sys.modules["fxars.execution.mt5_broker"] = self._real_broker_mod

    def _import_broker(self):
        # import بعد از نصب fake
        from fxars.execution.mt5_broker import MT5Broker, MT5BrokerError
        return MT5Broker, MT5BrokerError


# ===========================================================================
# 1. سازنده: safety checks
# ===========================================================================
class ConstructorTests(_MT5BrokerTestBase):
    def test_refuses_non_demo_account(self):
        self.fake._set_account(login=111, server="Alpari-Real", balance=10000.0, trade_mode=1)
        MT5Broker, MT5BrokerError = self._import_broker()
        with self.assertRaises(MT5BrokerError) as ctx:
            MT5Broker()
        self.assertIn("REFUSING", str(ctx.exception))

    def test_accepts_demo_server_with_demo_keyword(self):
        self.fake._set_account(login=222, server="Alpari-MT5-Demo", balance=100000.0, trade_mode=1)
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        self.assertIsNotNone(broker)

    def test_accepts_trade_mode_0(self):
        self.fake._set_account(login=333, server="SomeBroker", balance=10000.0, trade_mode=0)
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        self.assertIsNotNone(broker)

    def test_refuses_when_account_info_is_none(self):
        # account None by default
        MT5Broker, MT5BrokerError = self._import_broker()
        with self.assertRaises(MT5BrokerError) as ctx:
            MT5Broker()
        self.assertIn("account_info", str(ctx.exception))

    def test_initialize_failure_raises(self):
        # override initialize to fail
        self.fake.initialize = lambda: False
        self.fake.last_error = lambda: (10001, "connection failed")
        MT5Broker, MT5BrokerError = self._import_broker()
        with self.assertRaises(MT5BrokerError) as ctx:
            MT5Broker()
        self.assertIn("initialize failed", str(ctx.exception))


# ===========================================================================
# 2. submit: reject paths
# ===========================================================================
class SubmitRejectTests(_MT5BrokerTestBase):
    def setUp(self):
        super().setUp()
        self.fake._set_account(login=222, server="Alpari-MT5-Demo", balance=100000.0, trade_mode=1)

    def test_symbol_not_found(self):
        # symbol stays None
        self.fake._set_tick()
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        order, fills = broker.submit(_make_intent(), price=Decimal("1.09"), pip_size=Decimal("0.0001"))
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertEqual(fills, [])
        self.assertIn("symbol", order.message)

    def test_no_tick(self):
        self.fake._set_symbol()
        # tick remains None
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        order, fills = broker.submit(_make_intent(), price=Decimal("1.09"), pip_size=Decimal("0.0001"))
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertIn("tick", order.message)

    def test_volume_below_min(self):
        self.fake._set_symbol(volume_min=0.10)
        self.fake._set_tick()
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        order, fills = broker.submit(_make_intent(volume="0.01"), price=Decimal("1.09"), pip_size=Decimal("0.0001"))
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertIn("min", order.message)

    def test_order_send_returns_none(self):
        self.fake._set_symbol()
        self.fake._set_tick()
        # order_result None
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        order, fills = broker.submit(_make_intent(), price=Decimal("1.09"), pip_size=Decimal("0.0001"))
        self.assertEqual(order.status, OrderStatus.REJECTED)

    def test_order_send_non_done_retcode(self):
        self.fake._set_symbol()
        self.fake._set_tick()
        self.fake._set_order_result(retcode=10006, comment="Invalid stops")  # REJECT
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        order, fills = broker.submit(_make_intent(), price=Decimal("1.09"), pip_size=Decimal("0.0001"))
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertIn("retcode", order.message)


# ===========================================================================
# 3. submit: success path
# ===========================================================================
class SubmitSuccessTests(_MT5BrokerTestBase):
    def setUp(self):
        super().setUp()
        self.fake._set_account(login=222, server="Alpari-MT5-Demo", balance=100000.0, trade_mode=1)
        self.fake._set_symbol(volume_step=0.01)
        self.fake._set_tick(ask=1.09005, bid=1.08995)

    def test_buy_success(self):
        self.fake._set_order_result(
            retcode=10009, volume=0.10, price=1.09010, order=397978583,
        )
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        intent = _make_intent(side=Side.BUY, volume="0.10")
        order, fills = broker.submit(intent, price=Decimal("1.09"), pip_size=Decimal("0.0001"))

        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.broker_order_id, "397978583")
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].volume, Decimal("0.10"))
        self.assertEqual(fills[0].price, Decimal("1.0901"))

        # request sent
        req = self.fake._state["last_order_request"]
        self.assertEqual(req["symbol"], "EURUSD")
        self.assertEqual(req["type"], self.fake.ORDER_TYPE_BUY)
        self.assertEqual(req["magic"], 20261106)
        self.assertEqual(req["type_filling"], self.fake.ORDER_FILLING_FOK)
        self.assertEqual(req["deviation"], 20)

    def test_sell_success(self):
        self.fake._set_order_result(
            retcode=10009, volume=0.10, price=1.08995, order=397978584,
        )
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        intent = _make_intent(side=Side.SELL)
        order, fills = broker.submit(intent, price=Decimal("1.09"), pip_size=Decimal("0.0001"))
        self.assertEqual(order.status, OrderStatus.FILLED)
        req = self.fake._state["last_order_request"]
        self.assertEqual(req["type"], self.fake.ORDER_TYPE_SELL)

    def test_volume_rounded_down_to_step(self):
        self.fake._set_order_result(retcode=10009, volume=0.10, price=1.09000, order=1)
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        # 0.123 with step 0.01 → 0.12
        intent = _make_intent(volume="0.123")
        broker.submit(intent, price=Decimal("1.09"), pip_size=Decimal("0.0001"))
        req = self.fake._state["last_order_request"]
        self.assertAlmostEqual(req["volume"], 0.12, places=2)

    def test_sl_tp_included(self):
        self.fake._set_order_result(retcode=10009, volume=0.10, price=1.09000, order=1)
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        intent = _make_intent()
        broker.submit(intent, price=Decimal("1.09"), pip_size=Decimal("0.0001"))
        req = self.fake._state["last_order_request"]
        self.assertEqual(req["sl"], float(intent.stop_loss))
        self.assertEqual(req["tp"], float(intent.take_profit))

    def test_no_comment_field(self):
        """Alpari-Demo rejects comment sometimes; broker must not send it."""
        self.fake._set_order_result(retcode=10009, volume=0.10, price=1.09000, order=1)
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        broker.submit(_make_intent(), price=Decimal("1.09"), pip_size=Decimal("0.0001"))
        req = self.fake._state["last_order_request"]
        self.assertNotIn("comment", req)


# ===========================================================================
# 4. query
# ===========================================================================
class QueryTests(_MT5BrokerTestBase):
    def test_query_returns_none(self):
        self.fake._set_account(login=222, server="Alpari-MT5-Demo", balance=100000.0, trade_mode=1)
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        self.assertIsNone(broker.query("any-client-id"))


# ===========================================================================
# 5. shutdown
# ===========================================================================
class ShutdownTests(_MT5BrokerTestBase):
    def test_shutdown_calls_mt5(self):
        self.fake._set_account(login=222, server="Alpari-MT5-Demo", balance=100000.0, trade_mode=1)
        MT5Broker, _ = self._import_broker()
        broker = MT5Broker()
        broker.shutdown()
        self.assertTrue(self.fake._state["shutdown_called"])


if __name__ == "__main__":
    unittest.main()