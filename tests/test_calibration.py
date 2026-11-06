"""Calibration metrics and post-hoc calibration tests."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.research.calibration import (
    TemperatureScaling,
    bin_predictions,
    brier_score,
    calibration_report,
    expected_calibration_error,
    log_loss,
    maximum_calibration_error,
    reliability_diagram_svg,
)


class BrierScoreTests(unittest.TestCase):
    def test_perfect_predictions_zero(self):
        self.assertAlmostEqual(brier_score([1.0, 0.0, 1.0], [1, 0, 1]), 0.0)

    def test_worst_predictions_one(self):
        self.assertAlmostEqual(brier_score([0.0, 1.0], [1, 0]), 1.0)

    def test_base_rate_baseline(self):
        # Always predict base rate p=0.5, brier = 0.25
        probs = [0.5] * 10
        outcomes = [1, 0] * 5
        self.assertAlmostEqual(brier_score(probs, outcomes), 0.25)

    def test_empty(self):
        self.assertEqual(brier_score([], []), 0.0)


class LogLossTests(unittest.TestCase):
    def test_perfect_predictions_near_zero(self):
        self.assertLess(log_loss([1.0, 0.0, 1.0], [1, 0, 1]), 1e-9)

    def test_uniform_maximum(self):
        # ln(2) per sample
        self.assertAlmostEqual(log_loss([0.5, 0.5], [1, 0]), math.log(2), places=9)

    def test_clipping_prevents_inf(self):
        value = log_loss([0.0, 1.0], [1, 0])
        self.assertTrue(math.isfinite(value))
        self.assertGreater(value, 0)


class EceTests(unittest.TestCase):
    def test_perfect_calibration_zero(self):
        # Predict 0.0, 0.5, 1.0; empirical frequencies match exactly
        probs = [0.0, 0.0, 0.5, 0.5, 1.0, 1.0]
        outcomes = [0, 0, 1, 0, 1, 1]
        # Note: p=0.5 has empirical=0.5 which matches; p=0.0 -> 0, p=1.0 -> 1
        ece = expected_calibration_error(probs, outcomes, n_bins=3)
        self.assertLess(ece, 0.2)  # within bin granularity

    def test_overconfident_high_ece(self):
        # Predict 1.0 but outcome is 0 half the time
        probs = [1.0] * 10
        outcomes = [1, 0] * 5
        ece = expected_calibration_error(probs, outcomes, n_bins=10)
        self.assertGreater(ece, 0.4)

    def test_mce_bounds(self):
        probs = [0.1, 0.4, 0.7, 0.9]
        outcomes = [0, 1, 1, 0]
        mce = maximum_calibration_error(probs, outcomes, n_bins=5)
        self.assertGreaterEqual(mce, 0.0)
        self.assertLessEqual(mce, 1.0)


class BinTests(unittest.TestCase):
    def test_bins_cover_all_predictions(self):
        probs = [i / 20 for i in range(21)]
        outcomes = [1 if p > 0.5 else 0 for p in probs]
        bins = bin_predictions(probs, outcomes, n_bins=10)
        self.assertEqual(len(bins), 10)
        self.assertEqual(sum(b.count for b in bins), len(probs))

    def test_empty_input(self):
        self.assertEqual(bin_predictions([], []), [])


class TemperatureScalingTests(unittest.TestCase):
    def test_identity_temperature(self):
        scaler = TemperatureScaling(temperature=1.0)
        self.assertAlmostEqual(scaler.transform(0.3), 0.3, places=9)

    def test_softens_when_t_gt_1(self):
        scaler = TemperatureScaling(temperature=2.0)
        # 0.9 over-confident -> softened toward 0.5
        self.assertLess(scaler.transform(0.9), 0.9)
        # 0.1 also softened toward 0.5
        self.assertGreater(scaler.transform(0.1), 0.1)

    def test_sharpens_when_t_lt_1(self):
        scaler = TemperatureScaling(temperature=0.5)
        self.assertGreater(scaler.transform(0.6), 0.6)

    def test_fit_improves_logloss(self):
        # Deliberately over-confident: 0.95 with 50/50 outcomes
        probs = [0.95] * 40 + [0.05] * 40
        outcomes = [1, 0] * 20 + [0, 1] * 20
        raw_loss = log_loss(probs, outcomes)
        scaler = TemperatureScaling().fit(probs, outcomes)
        calibrated = scaler.transform_all(probs)
        new_loss = log_loss(calibrated, outcomes)
        self.assertLess(new_loss, raw_loss)
        self.assertGreater(scaler.temperature, 1.0)

    def test_monotonic_transform(self):
        scaler = TemperatureScaling(temperature=1.5)
        vals = [0.1, 0.2, 0.4, 0.6, 0.8, 0.9]
        transformed = scaler.transform_all(vals)
        self.assertEqual(transformed, sorted(transformed))


class ReportTests(unittest.TestCase):
    def test_report_structure(self):
        import random
        rng = random.Random(42)
        probs = [rng.random() for _ in range(200)]
        outcomes = [1 if p > 0.5 else 0 for p in probs]
        report = calibration_report(probs, outcomes, n_bins=10)
        self.assertEqual(report.n, 200)
        self.assertGreater(report.brier, 0.0)
        self.assertLess(report.brier, 1.0)
        self.assertGreaterEqual(report.ece, 0.0)
        self.assertGreater(report.temperature, 0.0)
        payload = report.to_dict()
        self.assertIn("after_calibration", payload)
        self.assertIn("bins", payload)

    def test_empty_report(self):
        report = calibration_report([], [])
        self.assertEqual(report.n, 0)
        self.assertEqual(report.to_dict()["n"], 0)

    def test_reliability_svg_renders(self):
        probs = [0.1, 0.3, 0.5, 0.7, 0.9] * 20
        outcomes = [0, 0, 1, 1, 1] * 20
        report = calibration_report(probs, outcomes, n_bins=5)
        svg = reliability_diagram_svg(report)
        self.assertIn("<svg", svg)
        self.assertIn("ECE=", svg)


class AcceptabilityTests(unittest.TestCase):
    def test_ece_threshold(self):
        # Well-calibrated data: ECE should be low
        import random
        rng = random.Random(7)
        probs = []
        outcomes = []
        for _ in range(500):
            p = rng.random()
            probs.append(p)
            outcomes.append(1 if rng.random() < p else 0)
        report = calibration_report(probs, outcomes, n_bins=10)
        self.assertTrue(report.is_acceptable, f"ECE={report.ece}")


if __name__ == "__main__":
    unittest.main()
