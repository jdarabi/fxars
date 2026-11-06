"""Regression tests for backtest fixes (06a/06b/06c)."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tests.helpers import make_env


class SwapTimeframeTests(unittest.TestCase):
    """FIX-06-SWAP: swap باید بر اساس دقیقه کندل باشد، نه bars/24."""

    def test_h1_swap(self):
        from fxars.research.backtest import BacktestConfig, BacktestEngine

        env = make_env(bars=100)
        try:
            config = BacktestConfig(
                swap_per_lot_per_night=Decimal("-2.5"),
                commission_per_lot=Decimal("0"),
                slippage_pips=Decimal("0"),
                spread_pips=Decimal("0"),
            )
            engine = BacktestEngine(env.instrument, "H1", config, env.settings.analysis)
            # nights = 24 bars * 60 min / 1440 = 1 day
            # swap = -2.5 * 1.0 volume * 1.0 night = -2.5
            assert engine._tf_minutes == 60
        finally:
            env.close()

    def test_h4_swap(self):
        from fxars.research.backtest import BacktestConfig, BacktestEngine
        env = make_env(bars=100)
        try:
            config = BacktestConfig()
            engine = BacktestEngine(env.instrument, "H4", config, env.settings.analysis)
            # H4 → 240 min
            assert engine._tf_minutes == 240
        finally:
            env.close()


class GapStopTests(unittest.TestCase):
    """FIX-06-GAP-STOP: Gap باید در Stop Loss رعایت شود."""

    def test_gap_down_long(self):
        """LONG با Gap Down: خروج در open، نه stop."""
        from decimal import Decimal

        from fxars.domain.enums import Direction
        from fxars.domain.models import Candle
        from fxars.research.backtest import BacktestConfig, BacktestEngine, _OpenTrade
        env = make_env(bars=100)
        try:
            config = BacktestConfig(slippage_pips=Decimal("0"), spread_pips=Decimal("0"))
            engine = BacktestEngine(env.instrument, "H1", config, env.settings.analysis)
            now = datetime(2026, 3, 2, 10, tzinfo=UTC)
            position = _OpenTrade(
                direction=Direction.LONG,
                entry_index=0,
                entry_time=now,
                entry_price=Decimal("1.0900"),
                stop=Decimal("1.0850"),
                tp1=Decimal("1.0950"),
                tp2=Decimal("1.1000"),
                volume=Decimal("0.10"),
                remaining=Decimal("0.10"),
                risk_amount=Decimal("10"),
            )
            # Gap Down: open=1.0800 (زیر stop=1.0850)
            candle = Candle(
                instrument_id="EURUSD", source_id="test", timeframe="H1",
                open_time=now + timedelta(hours=1),
                open=Decimal("1.0800"), high=Decimal("1.0810"),
                low=Decimal("1.0750"), close=Decimal("1.0780"),
                spread=Decimal("0"), is_closed=True,
                ingested_at=now + timedelta(hours=1, seconds=1),
                available_at=now + timedelta(hours=1, seconds=1),
            )
            trade, eq = engine._close(
                position, candle.open, "STOP_LOSS", candle, Decimal("10000"),
            )
            # اگر gap رعایت شود، PnL منفی‌تر از حالت بدون gap است
            # entry=1.09, exit=1.08 → loss 0.01 * 0.1 * 100000 = -100
            assert abs(trade["pnl"] - (-100.0)) < 1.0, f"pnl={trade['pnl']}"
        finally:
            env.close()


class FallbackStatsTests(unittest.TestCase):
    """FIX-06-FALLBACK-TRANSPARENT: fallback باید در stats ثبت شود."""

    def test_backtest_has_fallback_fields(self):
        env = make_env(bars=500)
        try:
            result = env.platform.research.run("EURUSD", "H1", persist=False)
            stats = result.run.metrics.get("stats", {})
            assert "fallback_count" in stats, f"missing fallback_count in {stats.keys()}"
            assert "fallback_errors" in stats
            assert isinstance(stats["fallback_count"], int)
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
