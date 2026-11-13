"""آزمون دروازه پذیرش پژوهش و الگوهای ضدّی (بخش ۹-۲ و ۹-۳ سند تکمیلی ۱.۱)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from fxars.config.decision import AcceptancePolicy
from fxars.domain.enums import BacktestSegment
from fxars.domain.models import BacktestRun
from fxars.research.acceptance import evaluate_acceptance, evaluate_run

from tests.helpers import make_env

GOOD_METRICS = {
    "trade_count": 300,
    "profit_factor": 1.45,
    "max_drawdown_pct": 0.08,
    "sharpe": 1.2,
    "calmar": 0.9,
    "costs": {"total": 120.0},
    "calibration": {"ece": 0.03},
    "locked_test": True,
    "walkforward": True,
}

GOOD_REGIMES = {
    "TREND": {"trade_count": 180},
    "RANGE": {"trade_count": 120},
}


class AcceptanceGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = AcceptancePolicy()

    def test_strong_oos_result_passes(self) -> None:
        report = evaluate_acceptance(
            GOOD_METRICS,
            policy=self.policy,
            train_metrics={"profit_factor": 1.5},
            test_metrics={"profit_factor": 1.45},
            regime_breakdown=GOOD_REGIMES,
            has_locked_test=True,
            has_walkforward=True,
        )
        self.assertTrue(report.passed, [item.code for item in report.failures])
        self.assertEqual(report.failures, ())
        self.assertEqual(report.anti_patterns, ())
        self.assertEqual(report.thresholds["min_oos_trades"], self.policy.min_oos_trades)

    def test_in_sample_result_rejected(self) -> None:
        report = evaluate_acceptance(GOOD_METRICS, policy=self.policy, is_oos=False)
        self.assertFalse(report.passed)
        codes = {check.code for check in report.failures}
        self.assertIn("OOS_SAMPLE", codes)

    def test_all_anti_patterns_detected(self) -> None:
        metrics = {
            "trade_count": 12,
            "profit_factor": 0.85,
            "max_drawdown_pct": 0.40,
            "sharpe": -0.4,
            "costs": {"total": 0.0},
        }
        report = evaluate_acceptance(
            metrics,
            policy=self.policy,
            train_metrics={"profit_factor": 3.0},
            test_metrics={"profit_factor": 1.0},
            regime_breakdown={"TREND": {"trade_count": 12}},
            has_locked_test=False,
            has_walkforward=False,
        )
        self.assertFalse(report.passed)
        codes = {check.code for check in report.failures}
        self.assertTrue({
            "OOS_SAMPLE", "PROFIT_FACTOR", "MAX_DRAWDOWN", "SHARPE_POSITIVE", "COSTS_MODELED",
        }.issubset(codes))
        anti = {item.code for item in report.anti_patterns}
        self.assertTrue({
            "TINY_SAMPLE", "OVERFIT_GAP", "IGNORED_COSTS", "NO_LOCKED_TEST",
            "NO_WALKFORWARD", "SINGLE_REGIME",
        }.issubset(anti))

    def test_train_test_gap_threshold(self) -> None:
        report = evaluate_acceptance(
            GOOD_METRICS,
            policy=self.policy,
            train_metrics={"profit_factor": 3.0},
            test_metrics={"profit_factor": 1.45},
            regime_breakdown=GOOD_REGIMES,
            has_locked_test=True,
            has_walkforward=True,
        )
        gap_check = next(item for item in report.checks if item.code == "TRAIN_TEST_GAP")
        self.assertFalse(gap_check.passed)
        self.assertIn("OVERFIT_GAP", {item.code for item in report.anti_patterns})

    def test_missing_calibration_skipped_until_reported(self) -> None:
        metrics = dict(GOOD_METRICS)
        metrics.pop("calibration")
        report = evaluate_acceptance(
            metrics, policy=self.policy, regime_breakdown=GOOD_REGIMES,
            has_locked_test=True, has_walkforward=True,
        )
        self.assertNotIn("CALIBRATION_ECE", {check.code for check in report.checks})
        self.assertTrue(report.passed)


class EvaluateRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=30)

    def tearDown(self) -> None:
        self.env.close()

    def run_for(self, segment: BacktestSegment, metrics: dict) -> BacktestRun:
        return BacktestRun(
            run_id=f"bt_{segment.value.lower()}", instrument_id="EURUSD", timeframe="H1",
            config={}, config_hash="hash", data_snapshot_id="snap", code_version="1.8.0",
            segment=segment, started_at=self.env.as_of - timedelta(days=5),
            finished_at=self.env.as_of, metrics=metrics, trades=(), equity_curve=(), seed=1,
        )

    def test_locked_test_run_uses_metrics_evidence(self) -> None:
        metrics = dict(GOOD_METRICS)
        metrics["regime_breakdown"] = GOOD_REGIMES
        report = evaluate_run(self.run_for(BacktestSegment.LOCKED_TEST, metrics), policy=AcceptancePolicy())
        self.assertTrue(report.passed, [item.code for item in report.failures])

    def test_train_segment_is_not_oos(self) -> None:
        metrics = dict(GOOD_METRICS)
        metrics["regime_breakdown"] = GOOD_REGIMES
        report = evaluate_run(self.run_for(BacktestSegment.TRAIN, metrics), policy=AcceptancePolicy())
        self.assertFalse(report.passed)
        self.assertIn("OOS_SAMPLE", {check.code for check in report.failures})

    def test_cli_gate_wiring(self) -> None:
        import argparse

        from fxars.cli.main import build_parser, cmd_research_gate

        parser = build_parser()
        self.assertTrue(isinstance(parser, argparse.ArgumentParser))
        args = parser.parse_args(["research-gate", "bt_locked_test", "--strict"])
        self.assertIs(args.func, cmd_research_gate)
        self.assertTrue(args.strict)
        self.assertEqual(args.run_id, "bt_locked_test")


if __name__ == "__main__":
    unittest.main()
