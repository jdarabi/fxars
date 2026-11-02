"""Triple Barrier Labeling (López de Prado, AFML ch. 3)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from fxars.domain.models import Candle


@dataclass(frozen=True)
class TripleBarrierConfig:
    """Barriers for a single label."""
    profit_atr: float = 1.5
    stop_atr: float = 1.0
    max_holding_bars: int = 24
    atr_period: int = 14

    def __post_init__(self) -> None:
        if self.profit_atr <= 0 or self.stop_atr <= 0:
            raise ValueError("profit_atr and stop_atr must be positive")
        if self.max_holding_bars < 1:
            raise ValueError("max_holding_bars must be >= 1")
        if self.atr_period < 2:
            raise ValueError("atr_period must be >= 2")


@dataclass(frozen=True)
class TripleBarrierLabel:
    """Label for a single entry point."""
    entry_index: int
    entry_price: float
    upper_barrier: float
    lower_barrier: float
    label: int
    exit_index: int
    exit_price: float
    bars_held: int
    atr: float

    @property
    def is_profit(self) -> bool:
        return self.label > 0

    @property
    def is_stop(self) -> bool:
        return self.label < 0

    @property
    def is_time(self) -> bool:
        return self.label == 0


def compute_atr_series(candles, period=14):
    """Wilder ATR, causal, None during warmup."""
    n = len(candles)
    if n == 0 or period < 2:
        return [None] * n
    ranges = []
    for i in range(n):
        high = float(candles[i].high)
        low = float(candles[i].low)
        if i == 0:
            ranges.append(high - low)
        else:
            prev_close = float(candles[i - 1].close)
            ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    out = [None] * n
    if n < period:
        return out
    seed = sum(ranges[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = (prev * (period - 1) + ranges[i]) / period
        out[i] = prev
    return out


def triple_barrier_labels(candles, config):
    """Label each entry point with the first barrier it hits."""
    n = len(candles)
    if n == 0:
        return []
    atr_series = compute_atr_series(candles, config.atr_period)
    labels = []
    for i in range(n):
        atr = atr_series[i]
        if atr is None or atr <= 0:
            continue
        entry_price = float(candles[i].close)
        upper = entry_price + config.profit_atr * atr
        lower = entry_price - config.stop_atr * atr
        max_end = min(i + config.max_holding_bars, n - 1)
        if max_end <= i:
            continue
        hit = 0
        exit_index = max_end
        exit_price = float(candles[max_end].close)
        for j in range(i + 1, max_end + 1):
            high = float(candles[j].high)
            low = float(candles[j].low)
            if high >= upper and low <= lower:
                hit = -1
                exit_index = j
                exit_price = lower
                break
            if high >= upper:
                hit = 1
                exit_index = j
                exit_price = upper
                break
            if low <= lower:
                hit = -1
                exit_index = j
                exit_price = lower
                break
        labels.append(TripleBarrierLabel(
            entry_index=i,
            entry_price=entry_price,
            upper_barrier=upper,
            lower_barrier=lower,
            label=hit,
            exit_index=exit_index,
            exit_price=exit_price,
            bars_held=exit_index - i,
            atr=atr,
        ))
    return labels


def label_statistics(labels):
    """Distribution and basic stats over a list of labels."""
    if not labels:
        return {"n": 0, "profits": 0, "stops": 0, "times": 0,
                "long_win_rate": None, "stop_rate": None, "time_rate": None,
                "avg_bars_held": None}
    n = len(labels)
    profits = sum(1 for lb in labels if lb.label > 0)
    stops = sum(1 for lb in labels if lb.label < 0)
    times = sum(1 for lb in labels if lb.label == 0)
    return {"n": n, "profits": profits, "stops": stops, "times": times,
            "long_win_rate": profits / n, "stop_rate": stops / n, "time_rate": times / n,
            "avg_bars_held": sum(lb.bars_held for lb in labels) / n,
            "avg_atr": sum(lb.atr for lb in labels) / n}


def labels_to_ml_dataset(candles, labels, feature_fn):
    """Convert labels into (X, y, indices) for ML."""
    X = []
    y = []
    indices = []
    for lb in labels:
        features = feature_fn(candles, lb.entry_index)
        if features is None:
            continue
        X.append(list(features))
        y.append(1 if lb.label > 0 else 0)
        indices.append(lb.entry_index)
    return X, y, indices
