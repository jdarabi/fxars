"""آزمون شبیه‌سازی انتخاب استراتژی: سود/زیان باید بر مبنای مضرب R باشد، نه درصد قیمت."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fxars.domain.models import Candle, Instrument
from fxars.live.strategy_selector import _simulate_simple


def _instrument(pip_size: str = "0.0001") -> Instrument:
    return Instrument(
        instrument_id="EURUSD",
        symbol="EURUSD",
        base_currency="EUR",
        quote_currency="USD",
        digits=5,
        point=Decimal("0.00001"),
        pip_size=Decimal(pip_size),
        contract_size=Decimal("100000"),
        min_lot=Decimal("0.01"),
        lot_step=Decimal("0.01"),
        max_lot=Decimal("100"),
        tick_size=Decimal("0.00001"),
        tick_value=Decimal("0.1"),
        profit_currency="USD",
        margin_rate=Decimal("0.01"),
        stop_level_points=0,
        freeze_level_points=0,
        swap_long=Decimal("0"),
        swap_short=Decimal("0"),
        commission_per_lot=Decimal("7"),
    )


def _candles(count: int = 60) -> list[Candle]:
    start = datetime(2026, 2, 1, 22, 0, tzinfo=UTC)
    rows: list[Candle] = []
    for index in range(count):
        open_time = start + timedelta(hours=index)
        rows.append(Candle(
            instrument_id="EURUSD", source_id="test", timeframe="H1",
            open_time=open_time, open=Decimal("1.10000"), high=Decimal("1.10000"),
            low=Decimal("1.10000"), close=Decimal("1.10000"),
            ingested_at=open_time, available_at=open_time + timedelta(hours=1),
        ))
    return rows


def _entry_once(signal: str, stop: float, target: float):
    def entry_fn(i: int, candles: list[Candle]):
        if i != 50:
            return None
        return (signal, float(candles[i].close), stop, target)

    return entry_fn


class SimulateSimpleTests(unittest.TestCase):
    def test_two_r_win_adds_two_percent_of_equity(self) -> None:
        candles = _candles()
        candles[51] = candles[51].__class__(
            instrument_id="EURUSD", source_id="test", timeframe="H1",
            open_time=candles[51].open_time, open=Decimal("1.10000"),
            high=Decimal("1.11000"), low=Decimal("1.09900"), close=Decimal("1.10900"),
            ingested_at=candles[51].ingested_at, available_at=candles[51].available_at,
        )
        result = _simulate_simple(
            candles, _instrument(), entry_fn=_entry_once("LONG", 1.09500, 1.11000), name="test",
        )
        self.assertEqual(result.trades, 1)
        self.assertAlmostEqual(result.net_profit, 200.0, places=6)
        self.assertAlmostEqual(result.profit_factor, 999.0, places=6)
        self.assertEqual(result.win_rate, 1.0)

    def test_one_r_loss_costs_one_percent_not_price_percent(self) -> None:
        candles = _candles()
        candles[51] = candles[51].__class__(
            instrument_id="EURUSD", source_id="test", timeframe="H1",
            open_time=candles[51].open_time, open=Decimal("1.10000"),
            high=Decimal("1.10050"), low=Decimal("1.09490"), close=Decimal("1.09510"),
            ingested_at=candles[51].ingested_at, available_at=candles[51].available_at,
        )
        result = _simulate_simple(
            candles, _instrument(), entry_fn=_entry_once("LONG", 1.09500, 1.11000), name="test",
        )
        self.assertEqual(result.trades, 1)
        self.assertAlmostEqual(result.net_profit, -100.0, places=6)
        self.assertEqual(result.win_rate, 0.0)

    def test_r_normalization_makes_instruments_comparable(self) -> None:
        """حرکت ۲R روی طلا با قیمت ۲۰۰۰ باید همان ۲٪ باشد، نه ۰٪."""
        candles = _candles()
        candles[51] = candles[51].__class__(
            instrument_id="XAUUSD", source_id="test", timeframe="H1",
            open_time=candles[51].open_time, open=Decimal("2000.00"),
            high=Decimal("2020.00"), low=Decimal("1995.00"), close=Decimal("2018.00"),
            ingested_at=candles[51].ingested_at, available_at=candles[51].available_at,
        )
        gold = _instrument(pip_size="0.1")
        result = _simulate_simple(
            candles, gold, entry_fn=_entry_once("LONG", 1990.0, 2020.0), name="gold",
        )
        self.assertEqual(result.trades, 1)
        self.assertAlmostEqual(result.net_profit, 200.0, places=6)


if __name__ == "__main__":
    unittest.main()
