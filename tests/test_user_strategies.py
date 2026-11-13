"""آزمون استراتژی‌های دستی کاربر: EMA20 + کندل فول‌بادی و سر و شانه (M5)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fxars.analysis.structure import Swing
from fxars.api.trading import _strategy_choice, _trend_candles
from fxars.core.errors import ValidationError
from fxars.domain.models import Candle, Instrument
from fxars.live.strategy_selector import (
    REQUIRED_TIMEFRAMES,
    HeadShouldersSetup,
    _fullbody_setup,
    _head_shoulders_setup,
    _head_shoulders_trigger,
    _latest_signal,
    _trend_directions,
    available_strategies,
    select_best_strategy,
    trend_history_bars,
)

PIP = Decimal("0.0001")
D = Decimal
START = datetime(2026, 2, 2, 0, 0, tzinfo=UTC)


def _instrument() -> Instrument:
    return Instrument(
        instrument_id="EURUSD",
        symbol="EURUSD",
        base_currency="EUR",
        quote_currency="USD",
        digits=5,
        point=Decimal("0.00001"),
        pip_size=PIP,
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


def _candle(index: int, open_: str, high: str, low: str, close: str) -> Candle:
    open_time = START + timedelta(minutes=5 * index)
    return Candle(
        instrument_id="EURUSD",
        source_id="test",
        timeframe="M5",
        open_time=open_time,
        open=D(open_),
        high=D(high),
        low=D(low),
        close=D(close),
        ingested_at=open_time,
        available_at=open_time + timedelta(minutes=5),
    )


def _ramp(count: int, start: str, step: str) -> list[Candle]:
    price = D(start)
    rows: list[Candle] = []
    for index in range(count):
        rows.append(_candle(index, str(price), str(price), str(price), str(price)))
        price += D(step)
    return rows


class FullBodyStrategyTests(unittest.TestCase):
    def test_green_full_body_above_ema_is_long(self) -> None:
        candle = _candle(0, "1.10010", "1.10200", "1.10010", "1.10200")
        setup = _fullbody_setup(candle, 1.10000, PIP)
        self.assertIsNotNone(setup)
        signal, entry, stop, target = setup
        self.assertEqual(signal, "LONG")
        self.assertAlmostEqual(entry, 1.10200, places=5)
        self.assertAlmostEqual(stop, 1.09990, places=5)   # ۲ پیپ زیر کندل
        self.assertAlmostEqual(target, 1.10580, places=5)  # ۲ برابر بدنه ۱۹ پیپی

    def test_red_full_body_below_ema_is_short(self) -> None:
        candle = _candle(0, "1.09990", "1.09990", "1.09800", "1.09800")
        setup = _fullbody_setup(candle, 1.10000, PIP)
        self.assertIsNotNone(setup)
        signal, entry, stop, target = setup
        self.assertEqual(signal, "SHORT")
        self.assertAlmostEqual(entry, 1.09800, places=5)
        self.assertAlmostEqual(stop, 1.10010, places=5)
        self.assertAlmostEqual(target, 1.09420, places=5)

    def test_candle_with_wick_is_rejected(self) -> None:
        candle = _candle(0, "1.10010", "1.10205", "1.10010", "1.10200")
        self.assertIsNone(_fullbody_setup(candle, 1.10000, PIP))

    def test_body_outside_ten_to_twenty_pips_is_rejected(self) -> None:
        small = _candle(0, "1.10010", "1.10090", "1.10010", "1.10090")  # ۸ پیپ
        large = _candle(0, "1.10010", "1.10260", "1.10010", "1.10260")  # ۲۵ پیپ
        self.assertIsNone(_fullbody_setup(small, 1.10000, PIP))
        self.assertIsNone(_fullbody_setup(large, 1.10000, PIP))

    def test_candle_not_fully_beyond_ema_is_rejected(self) -> None:
        candle = _candle(0, "1.10010", "1.10200", "1.10010", "1.10200")
        self.assertIsNone(_fullbody_setup(candle, 1.10100, PIP))

    def test_latest_signal_uses_last_closed_candle(self) -> None:
        candles = _ramp(50, "1.10000", "0.00005")
        candles.append(_candle(50, "1.10250", "1.10400", "1.10250", "1.10400"))
        signal = _latest_signal("EMA20/FullBody", candles, _instrument())
        self.assertIsNotNone(signal)
        side, entry, stop, target = signal
        self.assertEqual(side, "LONG")
        self.assertAlmostEqual(entry, 1.10400, places=5)
        self.assertAlmostEqual(stop, 1.10230, places=5)
        self.assertAlmostEqual(target, 1.10700, places=5)


class HeadShouldersPatternTests(unittest.TestCase):
    def test_inverse_pattern_right_shoulder_above_left(self) -> None:
        swings = [
            Swing(index=5, price=D("1.09900"), kind="LOW", confirmed_index=7),
            Swing(index=8, price=D("1.10050"), kind="HIGH", confirmed_index=10),
            Swing(index=10, price=D("1.09800"), kind="LOW", confirmed_index=12),
            Swing(index=12, price=D("1.09980"), kind="HIGH", confirmed_index=14),
            Swing(index=15, price=D("1.09920"), kind="LOW", confirmed_index=17),
        ]
        setup = _head_shoulders_setup(swings, 20)
        self.assertIsNotNone(setup)
        self.assertEqual(setup.direction, "LONG")
        self.assertEqual(setup.left_price, D("1.09900"))

    def test_normal_pattern_right_shoulder_below_left(self) -> None:
        swings = [
            Swing(index=5, price=D("1.10100"), kind="HIGH", confirmed_index=7),
            Swing(index=8, price=D("1.09950"), kind="LOW", confirmed_index=10),
            Swing(index=10, price=D("1.10200"), kind="HIGH", confirmed_index=12),
            Swing(index=12, price=D("1.10080"), kind="LOW", confirmed_index=14),
            Swing(index=15, price=D("1.10050"), kind="HIGH", confirmed_index=17),
        ]
        setup = _head_shoulders_setup(swings, 20)
        self.assertIsNotNone(setup)
        self.assertEqual(setup.direction, "SHORT")
        self.assertEqual(setup.left_price, D("1.10100"))

    def test_wrong_shoulder_order_is_rejected(self) -> None:
        swings = [
            Swing(index=5, price=D("1.09950"), kind="LOW", confirmed_index=7),
            Swing(index=8, price=D("1.10050"), kind="HIGH", confirmed_index=10),
            Swing(index=10, price=D("1.09800"), kind="LOW", confirmed_index=12),
            Swing(index=12, price=D("1.09980"), kind="HIGH", confirmed_index=14),
            Swing(index=15, price=D("1.09900"), kind="LOW", confirmed_index=17),
        ]
        self.assertIsNone(_head_shoulders_setup(swings, 20))

    def test_stale_pattern_is_rejected(self) -> None:
        swings = [
            Swing(index=5, price=D("1.09900"), kind="LOW", confirmed_index=7),
            Swing(index=8, price=D("1.10050"), kind="HIGH", confirmed_index=10),
            Swing(index=10, price=D("1.09800"), kind="LOW", confirmed_index=12),
            Swing(index=12, price=D("1.09980"), kind="HIGH", confirmed_index=14),
            Swing(index=15, price=D("1.09920"), kind="LOW", confirmed_index=17),
        ]
        self.assertIsNone(_head_shoulders_setup(swings, 40))

    def test_long_trigger_respects_left_shoulder_and_twenty_pips(self) -> None:
        setup = HeadShouldersSetup(direction="LONG", left_price=D("1.09900"), kind="LOW")
        candle = _candle(0, "1.10050", "1.10100", "1.10050", "1.10100")
        trigger = _head_shoulders_trigger(setup, candle, 1.10020, PIP)
        self.assertIsNotNone(trigger)
        signal, entry, stop, target = trigger
        self.assertEqual(signal, "LONG")
        self.assertAlmostEqual(entry, 1.10100, places=5)
        self.assertAlmostEqual(stop, 1.09880, places=5)
        self.assertAlmostEqual(target, 1.10300, places=5)

    def test_short_trigger_uses_mirrored_twenty_pip_target(self) -> None:
        setup = HeadShouldersSetup(direction="SHORT", left_price=D("1.10100"), kind="HIGH")
        candle = _candle(0, "1.10050", "1.10050", "1.10000", "1.10000")
        trigger = _head_shoulders_trigger(setup, candle, 1.10080, PIP)
        self.assertIsNotNone(trigger)
        signal, entry, stop, target = trigger
        self.assertEqual(signal, "SHORT")
        self.assertAlmostEqual(entry, 1.10000, places=5)
        self.assertAlmostEqual(stop, 1.10120, places=5)
        self.assertAlmostEqual(target, 1.09800, places=5)

    def test_trigger_rejects_candle_on_wrong_side_of_ema(self) -> None:
        setup = HeadShouldersSetup(direction="LONG", left_price=D("1.09900"), kind="LOW")
        candle = _candle(0, "1.10050", "1.10100", "1.10050", "1.10100")
        self.assertIsNone(_head_shoulders_trigger(setup, candle, 1.10150, PIP))


class StrategySelectionTests(unittest.TestCase):
    def _candles_with_signal(self) -> list[Candle]:
        candles = _ramp(119, "1.10000", "0.00005")
        candles.append(_candle(119, "1.10600", "1.10750", "1.10600", "1.10750"))
        return candles

    def test_catalog_marks_m5_requirement(self) -> None:
        catalog = {item["name"]: item for item in available_strategies()}
        self.assertEqual(REQUIRED_TIMEFRAMES["EMA20/FullBody"], "M5")
        self.assertEqual(catalog["EMA20/FullBody"]["timeframe"], "M5")
        self.assertEqual(catalog["H&S/Reversal"]["timeframe"], "M5")
        self.assertEqual(catalog["Trend/EMA"]["timeframe"], "")

    def test_manual_selection_wins_over_higher_score(self) -> None:
        data = select_best_strategy(
            self._candles_with_signal(), _instrument(), strategy="EMA20/FullBody",
        )
        self.assertEqual(data["selected"], "EMA20/FullBody")
        self.assertEqual(data["best"]["name"], "EMA20/FullBody")
        self.assertEqual(data["signal"], "LONG")
        self.assertAlmostEqual(data["entry"], 1.10750, places=5)

    def test_unknown_strategy_raises(self) -> None:
        with self.assertRaises(ValueError):
            select_best_strategy(
                self._candles_with_signal(), _instrument(), strategy="NOPE",
            )

    def test_api_accepts_empty_strategy_as_automatic(self) -> None:
        self.assertIsNone(_strategy_choice({"strategy": ""}, "H1"))
        self.assertIsNone(_strategy_choice({}, "H1"))

    def test_api_rejects_manual_strategy_on_wrong_timeframe(self) -> None:
        with self.assertRaises(ValidationError):
            _strategy_choice({"strategy": "EMA20/FullBody"}, "H1")
        self.assertEqual(
            _strategy_choice({"strategy": "EMA20/FullBody"}, "M5"),
            "EMA20/FullBody",
        )

    def test_api_rejects_unknown_strategy(self) -> None:
        with self.assertRaises(ValidationError):
            _strategy_choice({"strategy": "NOPE"}, "M5")


class TrendFilterTests(unittest.TestCase):
    def _h1(self, index: int, close: str, timeframe: str = "H1") -> Candle:
        open_time = START + timedelta(hours=index)
        return Candle(
            instrument_id="EURUSD",
            source_id="test",
            timeframe=timeframe,
            open_time=open_time,
            open=D(close),
            high=D(close),
            low=D(close),
            close=D(close),
            ingested_at=open_time,
            available_at=open_time + timedelta(hours=1),
        )

    def test_directions_use_last_closed_h1_bar_only(self) -> None:
        h1 = [
            self._h1(0, "1.1000"),
            self._h1(1, "1.1000"),
            self._h1(2, "1.1060"),
            self._h1(3, "1.1120"),
        ]
        m5 = [_candle(12, "1.1060", "1.1060", "1.1060", "1.1060"),
              _candle(24, "1.1060", "1.1060", "1.1060", "1.1060"),
              _candle(36, "1.1060", "1.1060", "1.1060", "1.1060"),
              _candle(48, "1.1060", "1.1060", "1.1060", "1.1060")]
        self.assertEqual(
            _trend_directions(m5, h1, period=2),
            [None, None, "UP", "UP"],
        )

    def test_directions_are_down_for_falling_h1(self) -> None:
        h1 = [self._h1(0, "1.1120"), self._h1(1, "1.1120"),
              self._h1(2, "1.1060"), self._h1(3, "1.1000")]
        m5 = [_candle(36, "1.1000", "1.1000", "1.1000", "1.1000")]
        self.assertEqual(_trend_directions(m5, h1, period=2), ["DOWN"])

    def test_latest_signal_is_blocked_against_h1_trend(self) -> None:
        candles = _ramp(119, "1.10000", "0.00005")
        candles.append(_candle(119, "1.10600", "1.10750", "1.10600", "1.10750"))
        down = ["DOWN"] * len(candles)
        up = ["UP"] * len(candles)
        self.assertIsNone(_latest_signal("EMA20/FullBody", candles, _instrument(), trend=down))
        signal = _latest_signal("EMA20/FullBody", candles, _instrument(), trend=up)
        self.assertIsNotNone(signal)
        self.assertEqual(signal[0], "LONG")

    def test_unknown_trend_direction_blocks_entry(self) -> None:
        candles = _ramp(119, "1.10000", "0.00005")
        candles.append(_candle(119, "1.10600", "1.10750", "1.10600", "1.10750"))
        unknown = [None] * len(candles)
        self.assertIsNone(_latest_signal("EMA20/FullBody", candles, _instrument(), trend=unknown))

    def _trend_history(self, rising: bool) -> list[Candle]:
        start = START - timedelta(days=4)
        rows: list[Candle] = []
        for index in range(60):
            price = D("1.1000") + D("0.0010") * index if rising else D("1.3000") - D("0.0010") * index
            open_time = start + timedelta(hours=index)
            rows.append(Candle(
                instrument_id="EURUSD", source_id="test", timeframe="H1",
                open_time=open_time, open=price, high=price, low=price, close=price,
                ingested_at=open_time, available_at=open_time + timedelta(hours=1),
            ))
        return rows

    def test_selection_reports_and_applies_trend_filter(self) -> None:
        candles = _ramp(119, "1.10000", "0.00005")
        candles.append(_candle(119, "1.10600", "1.10750", "1.10600", "1.10750"))

        bearish = select_best_strategy(
            candles, _instrument(), strategy="EMA20/FullBody",
            trend_candles=self._trend_history(rising=False),
        )
        self.assertEqual(bearish["signal"], "NO_TRADE")
        self.assertTrue(bearish["trend_filter"]["applied"])
        self.assertEqual(bearish["trend_filter"]["direction"], "DOWN")
        self.assertIn("روند H1", bearish["reason"])

        bullish = select_best_strategy(
            candles, _instrument(), strategy="EMA20/FullBody",
            trend_candles=self._trend_history(rising=True),
        )
        self.assertEqual(bullish["signal"], "LONG")
        self.assertEqual(bullish["trend_filter"]["direction"], "UP")

    def test_selection_without_trend_data_stays_unchanged(self) -> None:
        candles = _ramp(119, "1.10000", "0.00005")
        candles.append(_candle(119, "1.10600", "1.10750", "1.10600", "1.10750"))
        data = select_best_strategy(candles, _instrument(), strategy="EMA20/FullBody")
        self.assertEqual(data["signal"], "LONG")
        self.assertFalse(data["trend_filter"]["applied"])

    def test_empty_trend_history_fails_closed(self) -> None:
        candles = _ramp(119, "1.10000", "0.00005")
        candles.append(_candle(119, "1.10600", "1.10750", "1.10600", "1.10750"))
        data = select_best_strategy(
            candles, _instrument(), strategy="EMA20/FullBody", trend_candles=[],
        )
        self.assertTrue(data["trend_filter"]["applied"])
        self.assertEqual(data["signal"], "NO_TRADE")

    def test_trend_history_bars_covers_entry_history(self) -> None:
        self.assertEqual(trend_history_bars(2000), 226)
        self.assertEqual(trend_history_bars(100), 120)

    def test_api_fetches_h1_only_for_m5(self) -> None:
        class _Feed:
            def __init__(self) -> None:
                self.calls = []

            def fetch_recent(self, instrument_id, timeframe, count):
                self.calls.append((instrument_id, timeframe, count))
                return ["h1"]

        feed = _Feed()
        self.assertIsNone(_trend_candles(feed, "EURUSD", "H1", 500))
        self.assertEqual(feed.calls, [])
        self.assertEqual(_trend_candles(feed, "EURUSD", "M5", 2000), ["h1"])
        self.assertEqual(feed.calls, [("EURUSD", "H1", 226)])


if __name__ == "__main__":
    unittest.main()
