"""Regime filter in backtest tests (P3-4-ext2)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.research.backtest import BacktestConfig
from tests.helpers import make_env


class RegimeFilterConfigTests(unittest.TestCase):
    def test_default_is_empty(self):
        cfg = BacktestConfig()
        self.assertEqual(cfg.allowed_regimes, ())

    def test_tuple_accepted(self):
        cfg = BacktestConfig(allowed_regimes=("TRENDING_UP", "TRENDING_DOWN"))
        self.assertEqual(cfg.allowed_regimes, ("TRENDING_UP", "TRENDING_DOWN"))

    def test_list_normalized_to_tuple(self):
        cfg = BacktestConfig(allowed_regimes=["TRENDING_UP"])
        self.assertEqual(cfg.allowed_regimes, ("TRENDING_UP",))

    def test_from_settings_accepts_list(self):
        from fxars.config.settings import Settings
        s = Settings.from_dict({})
        cfg = BacktestConfig.from_settings(
            s.backtest,
            overrides={"allowed_regimes": ["TRENDING_UP"]},
        )
        self.assertEqual(cfg.allowed_regimes, ("TRENDING_UP",))


class RegimeFilterBacktestTests(unittest.TestCase):
    def test_filter_reduces_or_equals_trade_count(self):
        env = make_env(bars=500)
        try:
            base = env.platform.research.run("EURUSD", "H1", persist=False)
            filtered_cfg = BacktestConfig.from_settings(
                env.settings.backtest,
                overrides={"allowed_regimes": ["TRENDING_UP", "TRENDING_DOWN"]},
                min_signal_strength=env.settings.risk.min_signal_strength,
            )
            filtered = env.platform.research.run(
                "EURUSD", "H1", config=filtered_cfg, persist=False,
            )
            self.assertLessEqual(
                filtered.run.metrics["trade_count"],
                base.run.metrics["trade_count"],
            )
        finally:
            env.close()

    def test_filter_trades_are_only_in_allowed_regimes(self):
        env = make_env(bars=500)
        try:
            from fxars.research.regime import classify_regimes
            allowed = ("TRENDING_UP", "TRENDING_DOWN")
            cfg = BacktestConfig.from_settings(
                env.settings.backtest,
                overrides={"allowed_regimes": list(allowed)},
                min_signal_strength=env.settings.risk.min_signal_strength,
            )
            result = env.platform.research.run(
                "EURUSD", "H1", config=cfg, persist=False,
            )
            # Every trade must be in one of the allowed regimes
            candles = env.platform.candles.range(
                "EURUSD", "H1", source_id="demo_feed", closed_only=True,
            )
            labels = classify_regimes(candles)
            time_to_regime = {c.open_time: lb.regime for c, lb in zip(candles, labels)}
            from fxars.core.timeutil import parse_ts
            for trade in result.run.trades:
                entry_time = parse_ts(trade["entry_time"])
                regime = time_to_regime.get(entry_time)
                if regime is not None:
                    self.assertIn(regime, allowed)
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
