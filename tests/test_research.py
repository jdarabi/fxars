"""آزمون پژوهش: معیارها، اعتبارسنجی، بک‌تست و کنترل بیش‌برازش."""

from __future__ import annotations

import unittest
from decimal import Decimal

from fxars.domain.enums import BacktestSegment
from fxars.research.backtest import BacktestConfig
from fxars.research.metrics import compute_metrics, equity_returns
from fxars.research.montecarlo import monte_carlo_trades
from fxars.research.overfitting import deflated_sharpe_ratio, probability_of_backtest_overfitting
from fxars.research.protocol import (
    assert_disjoint,
    segment_range,
    split_segments,
    walk_forward_windows,
)
from tests.helpers import make_env


class MetricsTests(unittest.TestCase):
    def test_known_values(self) -> None:
        trades = [
            {"pnl": 100.0, "volume": 0.1, "bars_held": 2, "direction": "LONG", "r_multiple": 2.0,
             "commission": 1.0, "swap": 0.0, "spread_cost": 1.0, "slippage_cost": 0.5},
            {"pnl": -50.0, "volume": 0.1, "bars_held": 1, "direction": "SHORT", "r_multiple": -1.0,
             "commission": 1.0, "swap": 0.0, "spread_cost": 1.0, "slippage_cost": 0.5},
            {"pnl": 100.0, "volume": 0.1, "bars_held": 3, "direction": "LONG", "r_multiple": 2.0,
             "commission": 1.0, "swap": 0.0, "spread_cost": 1.0, "slippage_cost": 0.5},
        ]
        curve = [("0", 1000.0), ("1", 1100.0), ("2", 1050.0), ("3", 1150.0)]
        metrics = compute_metrics(trades, curve, initial_equity=1000.0, timeframe="H1")
        self.assertAlmostEqual(metrics["net_profit"], 150.0)
        self.assertAlmostEqual(metrics["profit_factor"], 4.0)
        self.assertAlmostEqual(metrics["win_rate"], 2 / 3, places=6)
        self.assertAlmostEqual(metrics["expectancy"], 50.0)
        self.assertAlmostEqual(metrics["max_drawdown"], 50.0)
        self.assertEqual(metrics["trade_count"], 3)
        self.assertGreater(metrics["costs"]["total"], 0)
        self.assertEqual(metrics["max_consecutive_wins"], 1)

    def test_no_trades(self) -> None:
        metrics = compute_metrics([], [("0", 1000.0)], initial_equity=1000.0, timeframe="H1")
        self.assertEqual(metrics["trade_count"], 0)
        self.assertIsNone(metrics["profit_factor"])
        self.assertEqual(metrics["net_profit"], 0.0)

    def test_equity_returns(self) -> None:
        returns = equity_returns([("0", 100.0), ("1", 110.0), ("2", 99.0)])
        self.assertAlmostEqual(returns[0], 0.1)
        self.assertAlmostEqual(returns[1], -0.1)


class ProtocolTests(unittest.TestCase):
    def test_split_disjoint_with_embargo(self) -> None:
        split = split_segments(1000, embargo_bars=5)
        assert_disjoint(split)
        self.assertGreater(split.train.size, 0)
        self.assertGreater(split.validation.size, 0)
        self.assertGreater(split.locked_test.size, 0)
        self.assertGreaterEqual(split.validation.start, split.train.end + 5)
        self.assertGreaterEqual(split.locked_test.start, split.validation.end + 5)

    def test_locked_test_independent(self) -> None:
        split = split_segments(500)
        self.assertGreater(split.locked_test.start, split.validation.end)
        self.assertGreater(split.validation.start, split.train.end)

    def test_segment_range(self) -> None:
        split = split_segments(500)
        self.assertEqual(segment_range(split, BacktestSegment.TRAIN).end, split.train.end)
        self.assertEqual(segment_range(split, BacktestSegment.ALL).size, 500)

    def test_invalid_split(self) -> None:
        from fxars.core.errors import ValidationError

        with self.assertRaises(ValidationError):
            split_segments(40)
        with self.assertRaises(ValidationError):
            split_segments(500, train_fraction=0.7, validation_fraction=0.25)

    def test_walk_forward_windows(self) -> None:
        windows = walk_forward_windows(1200, train_bars=400, test_bars=100, step_bars=100)
        self.assertGreater(len(windows), 0)
        for window in windows:
            self.assertLess(window.train_start, window.train_end)
            self.assertEqual(window.test_start, window.train_end)
            self.assertLessEqual(window.test_end, 1200)


class OverfittingTests(unittest.TestCase):
    def test_dsr_range(self) -> None:
        returns = [0.001, -0.0005, 0.002, 0.0, 0.0015] * 20
        result = deflated_sharpe_ratio(returns, trials=10)
        self.assertIsNotNone(result["dsr"])
        self.assertGreaterEqual(result["dsr"], 0.0)
        self.assertLessEqual(result["dsr"], 1.0)

    def test_pbo(self) -> None:
        import random

        rng = random.Random(3)
        matrix = [[rng.gauss(0.0001, 0.001) for _ in range(200)] for _ in range(4)]
        result = probability_of_backtest_overfitting(matrix, blocks=10)
        self.assertIsNotNone(result["pbo"])
        self.assertGreater(result["splits"], 0)
        self.assertEqual(result["strategies"], 4)

    def test_monte_carlo_deterministic(self) -> None:
        trades = [{"pnl": 50.0, "commission": 1.0, "slippage_cost": 1.0},
                  {"pnl": -30.0, "commission": 1.0, "slippage_cost": 1.0}] * 10
        first = monte_carlo_trades(trades, initial_equity=1000, runs=50, seed=5)
        second = monte_carlo_trades(trades, initial_equity=1000, runs=50, seed=5)
        self.assertEqual(first["net_profit"], second["net_profit"])
        self.assertEqual(first["probability_of_loss"], second["probability_of_loss"])


class BacktestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=500)

    def tearDown(self) -> None:
        self.env.close()

    def test_backtest_runs_and_costs_are_split(self) -> None:
        result = self.env.platform.research.run("EURUSD", "H1", persist=True)
        metrics = result.run.metrics
        self.assertIn("trade_count", metrics)
        self.assertIn("costs", metrics)
        for key in ("spread", "commission", "swap", "slippage", "total"):
            self.assertIn(key, metrics["costs"])
        if metrics["trade_count"] > 0:
            self.assertGreater(metrics["costs"]["spread"], 0)
            self.assertGreater(metrics["costs"]["commission"], 0)
        self.assertEqual(len(result.output.equity_curve), 500 - self.env.settings.analysis.min_bars + 1)

    def test_entry_never_before_decision(self) -> None:
        result = self.env.platform.research.run("EURUSD", "H1")
        for trade in result.run.trades:
            self.assertLessEqual(trade["entry_time"], trade["exit_time"])
            self.assertGreaterEqual(trade["bars_held"], 1)

    def test_config_override(self) -> None:
        config = BacktestConfig.from_settings(self.env.settings.backtest, overrides={"stop_buffer_pips": 9})
        self.assertEqual(config.stop_buffer_pips, Decimal("9"))
        with self.assertRaises(ValueError):
            BacktestConfig.from_settings(self.env.settings.backtest, overrides={"unknown": 1})

    def test_segments_do_not_overlap(self) -> None:
        split = split_segments(500)
        assert_disjoint(split)


if __name__ == "__main__":
    unittest.main()
