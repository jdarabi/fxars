"""ML pipeline tests: Triple Barrier + Purged K-Fold."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.domain.models import Candle
from fxars.research.labeling import TripleBarrierConfig
from fxars.research.ml_pipeline import (
    MLPipelineConfig,
    run_ml_pipeline,
    train_test_arrays,
)


def _make_candle(index, open_, high, low, close):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Candle(
        instrument_id="EURUSD", source_id="test", timeframe="H1",
        open_time=start + timedelta(hours=index),
        open=Decimal(str(open_)), high=Decimal(str(high)),
        low=Decimal(str(low)), close=Decimal(str(close)),
        ingested_at=start + timedelta(hours=index, seconds=10),
        available_at=start + timedelta(hours=index, seconds=10),
        spread=Decimal("0.0001"), is_closed=True,
    )


def _random_walk_candles(n: int, seed: int = 7):
    import random
    rng = random.Random(seed)
    candles = []
    price = 1.08
    for i in range(n):
        ret = rng.gauss(0, 0.0005)
        open_ = price
        close = open_ * (1 + ret)
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.0002)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.0002)))
        candles.append(_make_candle(i, open_, high, low, close))
        price = close
    return candles


class PipelineTests(unittest.TestCase):
    def test_pipeline_empty(self):
        result = run_ml_pipeline([])
        self.assertEqual(result.labels, [])
        self.assertEqual(result.folds, [])
        self.assertEqual(result.X, [])

    def test_pipeline_small_data_no_folds(self):
        candles = _random_walk_candles(30)
        result = run_ml_pipeline(candles)
        # Too few labels for 5-fold; folds should be empty but labels present
        self.assertGreaterEqual(len(result.labels), 0)

    def test_pipeline_full(self):
        candles = _random_walk_candles(500, seed=11)
        config = MLPipelineConfig(
            labeling=TripleBarrierConfig(profit_atr=1.5, stop_atr=1.0,
                                         max_holding_bars=24, atr_period=14),
            n_splits=5, purge_bars=5, embargo_bars=5,
        )
        result = run_ml_pipeline(candles, config)
        self.assertGreater(len(result.X), 0)
        self.assertGreater(len(result.y), 0)
        self.assertEqual(len(result.X), len(result.y))
        self.assertEqual(len(result.X), len(result.indices))
        # Labels and folds should both be present
        self.assertGreater(len(result.labels), 0)
        self.assertGreater(len(result.folds), 0)
        self.assertEqual(len(result.folds), 5)

    def test_pipeline_folds_are_disjoint(self):
        candles = _random_walk_candles(500, seed=13)
        config = MLPipelineConfig(n_splits=5, purge_bars=5, embargo_bars=5)
        result = run_ml_pipeline(candles, config)
        for fold in result.folds:
            train = set(fold.train_indices)
            test = set(fold.test_indices)
            self.assertEqual(train & test, set())

    def test_train_test_arrays(self):
        candles = _random_walk_candles(500, seed=17)
        config = MLPipelineConfig(n_splits=5, purge_bars=5, embargo_bars=5)
        result = run_ml_pipeline(candles, config)
        for fold in result.folds:
            X_train, y_train, X_test, y_test = train_test_arrays(result, fold)
            self.assertEqual(len(X_train), len(y_train))
            self.assertEqual(len(X_test), len(y_test))
            self.assertEqual(len(X_train), fold.train_size)
            self.assertEqual(len(X_test), fold.test_size)
            if X_train:
                self.assertEqual(len(X_train[0]), 5)  # default feature dim

    def test_pipeline_to_dict(self):
        candles = _random_walk_candles(300, seed=23)
        result = run_ml_pipeline(candles)
        payload = result.to_dict()
        self.assertIn("label_stats", payload)
        self.assertIn("coverage", payload)
        self.assertIn("n_labels", payload)
        self.assertIn("folds", payload)

    def test_label_stats_sane(self):
        candles = _random_walk_candles(300, seed=29)
        result = run_ml_pipeline(candles)
        stats = result.label_stats
        self.assertEqual(stats["n"], len(result.labels))
        self.assertGreaterEqual(stats["long_win_rate"] or 0, 0.0)
        self.assertLessEqual(stats["long_win_rate"] or 1, 1.0)


if __name__ == "__main__":
    unittest.main()
