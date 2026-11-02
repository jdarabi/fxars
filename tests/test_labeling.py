"""Triple Barrier Labeling tests."""
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
from fxars.research.labeling import (
    TripleBarrierConfig,
    compute_atr_series,
    label_statistics,
    labels_to_ml_dataset,
    triple_barrier_labels,
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


class ATRTests(unittest.TestCase):
    def test_atr_warmup_none(self):
        candles = [_make_candle(i, 1.0, 1.01, 0.99, 1.0) for i in range(5)]
        series = compute_atr_series(candles, period=14)
        self.assertTrue(all(v is None for v in series))

    def test_atr_positive_after_warmup(self):
        candles = [_make_candle(i, 1.0 + 0.001 * i, 1.02 + 0.001 * i, 0.98 + 0.001 * i, 1.0 + 0.001 * i)
                   for i in range(30)]
        series = compute_atr_series(candles, period=14)
        valid = [v for v in series if v is not None]
        self.assertGreater(len(valid), 0)
        self.assertTrue(all(v > 0 for v in valid))

    def test_empty_series(self):
        self.assertEqual(compute_atr_series([], period=14), [])


class LabelingTests(unittest.TestCase):
    def _base_config(self):
        return TripleBarrierConfig(profit_atr=1.5, stop_atr=1.0,
                                   max_holding_bars=10, atr_period=3)

    def test_profit_barrier_hit(self):
        candles = [_make_candle(i, 1.0, 1.005, 0.995, 1.0) for i in range(10)]
        candles.append(_make_candle(10, 1.0, 1.10, 1.0, 1.09))
        labels = triple_barrier_labels(candles, self._base_config())
        profit_labels = [lb for lb in labels if lb.label > 0]
        self.assertGreater(len(profit_labels), 0)

    def test_stop_barrier_hit(self):
        candles = [_make_candle(i, 1.0, 1.005, 0.995, 1.0) for i in range(10)]
        candles.append(_make_candle(10, 1.0, 1.0, 0.90, 0.91))
        labels = triple_barrier_labels(candles, self._base_config())
        stop_labels = [lb for lb in labels if lb.label < 0]
        self.assertGreater(len(stop_labels), 0)

    def test_time_barrier_default(self):
        candles = [_make_candle(i, 1.0 + 0.0001 * i, 1.001 + 0.0001 * i, 0.999 + 0.0001 * i, 1.0 + 0.0001 * i)
                   for i in range(40)]
        config = TripleBarrierConfig(profit_atr=100.0, stop_atr=100.0,
                                     max_holding_bars=5, atr_period=3)
        labels = triple_barrier_labels(candles, config)
        time_labels = [lb for lb in labels if lb.label == 0]
        self.assertGreater(len(time_labels), 0)

    def test_no_labels_when_data_too_short(self):
        candles = [_make_candle(i, 1.0, 1.01, 0.99, 1.0) for i in range(3)]
        config = TripleBarrierConfig(atr_period=14)
        labels = triple_barrier_labels(candles, config)
        self.assertEqual(labels, [])

    def test_both_barriers_hit_in_same_bar_prefers_stop(self):
        candles = [_make_candle(i, 1.0, 1.005, 0.995, 1.0) for i in range(10)]
        candles.append(_make_candle(10, 1.0, 1.20, 0.80, 1.0))
        labels = triple_barrier_labels(candles, self._base_config())
        lb9 = [lb for lb in labels if lb.entry_index == 9]
        if lb9:
            self.assertLessEqual(lb9[0].label, 0)

    def test_invalid_config(self):
        with self.assertRaises(ValueError):
            TripleBarrierConfig(profit_atr=-1.0)
        with self.assertRaises(ValueError):
            TripleBarrierConfig(max_holding_bars=0)


class StatisticsTests(unittest.TestCase):
    def test_empty(self):
        stats = label_statistics([])
        self.assertEqual(stats["n"], 0)
        self.assertIsNone(stats["long_win_rate"])

    def test_counts(self):
        candles = [_make_candle(i, 1.0, 1.005, 0.995, 1.0) for i in range(10)]
        candles.append(_make_candle(10, 1.0, 1.10, 1.0, 1.09))
        candles.append(_make_candle(11, 1.0, 1.0, 0.90, 0.91))
        config = TripleBarrierConfig(profit_atr=1.5, stop_atr=1.0,
                                     max_holding_bars=5, atr_period=3)
        labels = triple_barrier_labels(candles, config)
        stats = label_statistics(labels)
        self.assertEqual(stats["n"], len(labels))
        self.assertIsNotNone(stats["long_win_rate"])


class MLDatasetTests(unittest.TestCase):
    def test_dataset_shape(self):
        candles = [_make_candle(i, 1.0, 1.01, 0.99, 1.0) for i in range(20)]
        candles.append(_make_candle(20, 1.0, 1.10, 1.0, 1.09))
        config = TripleBarrierConfig(profit_atr=1.5, stop_atr=1.0,
                                     max_holding_bars=5, atr_period=3)
        labels = triple_barrier_labels(candles, config)
        def features(cs, idx):
            return [float(cs[idx].close), float(cs[idx].high - cs[idx].low)]
        X, y, indices = labels_to_ml_dataset(candles, labels, features)
        self.assertEqual(len(X), len(y))
        self.assertEqual(len(X), len(indices))
        if X:
            self.assertEqual(len(X[0]), 2)
            self.assertTrue(all(v in (0, 1) for v in y))


if __name__ == "__main__":
    unittest.main()
