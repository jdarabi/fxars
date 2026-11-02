"""Regime detection tests."""
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
from fxars.research.regime import (
    ALL_REGIMES, HIGH_VOL, LOW_VOL, RANGING, TRENDING_DOWN, TRENDING_UP,
    RegimeConfig, classify_regimes, regime_at, regime_breakdown, regime_distribution,
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


def _trending_up(n):
    # Strong clean uptrend; small wick so ATR stays low relative to trend
    candles = []
    for i in range(n):
        o = 1.0 + i * 0.001
        c = o + 0.0008
        candles.append(_make_candle(i, o, c + 0.00005, o - 0.00005, c))
    return candles


def _trending_down(n):
    candles = []
    for i in range(n):
        o = 1.0 - i * 0.001
        c = o - 0.0008
        candles.append(_make_candle(i, o, o + 0.00005, c - 0.00005, c))
    return candles


def _flat(n):
    return [_make_candle(i, 1.0, 1.0001, 0.9999, 1.0) for i in range(n)]


class RegimeConfigTests(unittest.TestCase):
    def test_invalid_ema(self):
        with self.assertRaises(ValueError):
            RegimeConfig(ema_fast=50, ema_slow=20)
    def test_invalid_percentiles(self):
        with self.assertRaises(ValueError):
            RegimeConfig(vol_low_percentile=90, vol_high_percentile=80)
    def test_invalid_atr(self):
        with self.assertRaises(ValueError):
            RegimeConfig(atr_period=1)


class ClassificationTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(classify_regimes([]), [])

    def test_trending_up(self):
        candles = _trending_up(200)
        labels = classify_regimes(candles)
        up = sum(1 for lb in labels if lb.regime == TRENDING_UP)
        self.assertGreater(up, 30)

    def test_trending_down(self):
        candles = _trending_down(200)
        labels = classify_regimes(candles)
        down = sum(1 for lb in labels if lb.regime == TRENDING_DOWN)
        self.assertGreater(down, 30)

    def test_flat_is_ranging_or_low_vol(self):
        candles = _flat(200)
        labels = classify_regimes(candles)
        ranging = sum(1 for lb in labels if lb.regime == RANGING)
        low_vol = sum(1 for lb in labels if lb.regime == LOW_VOL)
        self.assertGreater(ranging + low_vol, len(labels) * 0.8)

    def test_all_labels_valid(self):
        labels = classify_regimes(_trending_up(100))
        for lb in labels:
            self.assertIn(lb.regime, ALL_REGIMES)

    def test_warmup_is_ranging(self):
        labels = classify_regimes(_trending_up(100))
        for lb in labels[:49]:
            self.assertEqual(lb.regime, RANGING)


class DistributionTests(unittest.TestCase):
    def test_distribution_sums(self):
        labels = classify_regimes(_trending_up(200))
        dist = regime_distribution(labels)
        self.assertEqual(sum(dist.values()), len(labels))
        for r in ALL_REGIMES:
            self.assertIn(r, dist)

    def test_regime_at(self):
        labels = classify_regimes(_trending_up(200))
        self.assertEqual(regime_at(labels, 0), labels[0].regime)
        self.assertIsNone(regime_at(labels, -1))
        self.assertIsNone(regime_at(labels, len(labels)))


class BreakdownTests(unittest.TestCase):
    def test_breakdown_empty(self):
        result = regime_breakdown([], [], [])
        for r in ALL_REGIMES:
            self.assertEqual(result[r]["count"], 0)

    def test_breakdown_counts_trades(self):
        labels = classify_regimes(_trending_up(200))
        entries = [100, 101, 102, 150]
        pnls = [10.0, -5.0, 3.0, 8.0]
        result = regime_breakdown(labels, entries, pnls)
        total = sum(b["count"] for b in result.values())
        self.assertEqual(total, len(entries))
        total_pnl = sum(b["total_pnl"] for b in result.values())
        self.assertAlmostEqual(total_pnl, sum(pnls))


if __name__ == "__main__":
    unittest.main()
