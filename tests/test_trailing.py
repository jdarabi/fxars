"""Unit tests for fxars.execution.trailing.apply_trailing_sl."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.execution.trailing import _buffer_points, _new_sl_for_position, apply_trailing_sl


def _make_position(
    ticket=1, symbol="EURUSD", ptype=0, price_open=1.08000,
    price_current=1.09000, sl=0.0, tp=1.10000,
    *, symbol_digits=5, symbol_point=0.00001,
):
    si = types.SimpleNamespace(
        name=symbol, digits=symbol_digits, point=symbol_point,
        volume_min=0.01, volume_max=100.0, volume_step=0.01,
    )
    pos = types.SimpleNamespace(
        ticket=ticket, symbol=symbol, type=ptype,
        price_open=price_open, price_current=price_current,
        sl=sl, tp=tp,
        symbol_info=si,
    )
    return pos


def _make_fake_mt5(positions):
    fake = types.ModuleType("MetaTrader5")
    fake.TRADE_ACTION_SLTP = 6
    fake.TRADE_RETCODE_DONE = 10009

    class Result:
        def __init__(self, retcode=10009):
            self.retcode = retcode

    state = {"requests": [], "next_retcode": 10009}

    def positions_get():
        return positions

    def symbol_info(name):
        # نمادهای ناشناخته → None (شبیه MT5 واقعی)
        for p in positions:
            if p.symbol == name and p.symbol_info is not None:
                return p.symbol_info
        return None

    def order_send(request):
        state["requests"].append(request)
        return Result(state["next_retcode"])

    fake.positions_get = positions_get
    fake.symbol_info = symbol_info
    fake.order_send = order_send
    fake._state = state
    return fake


class BufferPointsTests(unittest.TestCase):
    def test_jpy_digits_3(self):
        self.assertEqual(_buffer_points(3, 40), 40)

    def test_xau_digits_2(self):
        self.assertEqual(_buffer_points(2, 40), 400)

    def test_forex_digits_5(self):
        self.assertEqual(_buffer_points(5, 40), 400)

    def test_unknown_digits_defaults_forex(self):
        self.assertEqual(_buffer_points(4, 20), 200)


class NewSlTests(unittest.TestCase):
    def test_buy_trailing_below_current(self):
        p = _make_position(ptype=0, price_open=1.08000, price_current=1.09000, symbol_digits=5)
        new_sl, side = _new_sl_for_position(p, 40)
        self.assertEqual(side, "BUY")
        self.assertAlmostEqual(new_sl, 1.08600, places=5)

    def test_buy_never_below_entry(self):
        p = _make_position(ptype=0, price_open=1.08000, price_current=1.08100, symbol_digits=5)
        new_sl, _ = _new_sl_for_position(p, 40)
        self.assertAlmostEqual(new_sl, 1.08000, places=5)

    def test_sell_trailing_above_current(self):
        p = _make_position(ptype=1, price_open=1.09000, price_current=1.08000, symbol_digits=5)
        new_sl, side = _new_sl_for_position(p, 40)
        self.assertEqual(side, "SELL")
        self.assertAlmostEqual(new_sl, 1.08400, places=5)

    def test_sell_never_above_entry(self):
        p = _make_position(ptype=1, price_open=1.09000, price_current=1.08900, symbol_digits=5)
        new_sl, _ = _new_sl_for_position(p, 40)
        self.assertAlmostEqual(new_sl, 1.09000, places=5)

    def test_jpy_buffer(self):
        p = _make_position(
            symbol="USDJPY", ptype=0, price_open=150.0, price_current=150.5,
            symbol_digits=3, symbol_point=0.001,
        )
        new_sl, _ = _new_sl_for_position(p, 40)
        self.assertAlmostEqual(new_sl, 150.460, places=3)


class ApplyTrailingTests(unittest.TestCase):
    def test_no_positions(self):
        fake = _make_fake_mt5([])
        self.assertEqual(apply_trailing_sl(mt5=fake), 0)

    def test_buy_updated(self):
        pos = _make_position(ptype=0, sl=0.0, price_current=1.09000)
        fake = _make_fake_mt5([pos])
        updated = apply_trailing_sl(trailing_pips=40, mt5=fake)
        self.assertEqual(updated, 1)
        req = fake._state["requests"][0]
        self.assertEqual(req["action"], fake.TRADE_ACTION_SLTP)
        self.assertEqual(req["position"], 1)
        self.assertAlmostEqual(req["sl"], 1.08600, places=5)

    def test_sell_updated(self):
        pos = _make_position(ptype=1, price_open=1.09000, price_current=1.08000, sl=0.0)
        fake = _make_fake_mt5([pos])
        updated = apply_trailing_sl(trailing_pips=40, mt5=fake)
        self.assertEqual(updated, 1)
        req = fake._state["requests"][0]
        self.assertAlmostEqual(req["sl"], 1.08400, places=5)

    def test_no_worse_sl_for_buy(self):
        pos = _make_position(ptype=0, sl=1.08700, price_current=1.09000)
        fake = _make_fake_mt5([pos])
        updated = apply_trailing_sl(trailing_pips=40, mt5=fake)
        self.assertEqual(updated, 0)

    def test_no_worse_sl_for_sell(self):
        pos = _make_position(ptype=1, price_open=1.09000, price_current=1.08000, sl=1.08300)
        fake = _make_fake_mt5([pos])
        updated = apply_trailing_sl(trailing_pips=40, mt5=fake)
        self.assertEqual(updated, 0)

    def test_order_send_failure_does_not_raise(self):
        pos = _make_position(ptype=0, sl=0.0)
        fake = _make_fake_mt5([pos])
        fake._state["next_retcode"] = 10006
        updated = apply_trailing_sl(trailing_pips=40, mt5=fake)
        self.assertEqual(updated, 0)

    def test_missing_symbol_info_skipped(self):
        pos = _make_position(ptype=0, sl=0.0, symbol="UNKNOWN")
        pos.symbol_info = None  # ← نماد ناشناخته
        fake = _make_fake_mt5([pos])
        updated = apply_trailing_sl(trailing_pips=40, mt5=fake)
        self.assertEqual(updated, 0)


if __name__ == "__main__":
    unittest.main()
