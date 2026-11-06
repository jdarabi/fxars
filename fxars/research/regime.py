"""Market regime detection for backtest performance attribution."""
from __future__ import annotations

from dataclasses import dataclass

TRENDING_UP = "TRENDING_UP"
TRENDING_DOWN = "TRENDING_DOWN"
RANGING = "RANGING"
HIGH_VOL = "HIGH_VOL"
LOW_VOL = "LOW_VOL"

ALL_REGIMES = (TRENDING_UP, TRENDING_DOWN, RANGING, HIGH_VOL, LOW_VOL)


@dataclass(frozen=True)
class RegimeConfig:
    """Parameters for regime classification."""
    ema_fast: int = 20
    ema_slow: int = 50
    atr_period: int = 14
    vol_lookback: int = 100
    vol_high_percentile: float = 80.0
    vol_low_percentile: float = 20.0
    trend_slope_threshold: float = 0.05

    def __post_init__(self) -> None:
        if self.ema_fast < 2 or self.ema_slow < 2:
            raise ValueError("EMA periods must be >= 2")
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast must be < ema_slow")
        if self.atr_period < 2:
            raise ValueError("atr_period must be >= 2")
        if not (0 < self.vol_low_percentile < self.vol_high_percentile < 100):
            raise ValueError("vol percentiles must satisfy 0 < low < high < 100")


@dataclass(frozen=True)
class RegimeLabel:
    index: int
    regime: str
    ema_fast: float | None
    ema_slow: float | None
    atr: float | None
    atr_percentile: float | None


def _ema(values, period):
    n = len(values)
    out = [None] * n
    if n < period or period < 2:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    mult = 2.0 / (period + 1.0)
    prev = seed
    for i in range(period, n):
        prev = (values[i] - prev) * mult + prev
        out[i] = prev
    return out


def _wilder_atr(candles, period):
    n = len(candles)
    if n < period or period < 2:
        return [None] * n
    trs = []
    for i in range(n):
        hi = float(candles[i].high)
        lo = float(candles[i].low)
        if i == 0:
            trs.append(hi - lo)
        else:
            pc = float(candles[i - 1].close)
            trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    out = [None] * n
    seed = sum(trs[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


def _atr_percentile_series(atr, window):
    """FIX: midpoint rank so constant series yields ~50, not 100."""
    n = len(atr)
    out = [None] * n
    for i in range(n):
        v = atr[i]
        if v is None:
            continue
        start = max(0, i - window + 1)
        sample = [x for x in atr[start:i + 1] if x is not None]
        if len(sample) < 10:
            continue
        below_strict = sum(1 for x in sample if x < v)
        equal = sum(1 for x in sample if x == v)
        mid_rank = (below_strict + 0.5 * equal) / len(sample)
        out[i] = 100.0 * mid_rank
    return out


def classify_regimes(candles, config=None):
    """Classify each candle.

    Priority order:
      1. LOW_VOL (compression): edges unreliable -> skip trend
      2. Clear trend (|slope_norm| > threshold): TRENDING_UP/DOWN
      3. HIGH_VOL: only when trend is unclear
      4. RANGING: default
    """
    config = config or RegimeConfig()
    n = len(candles)
    if n == 0:
        return []
    closes = [float(c.close) for c in candles]
    ema_fast = _ema(closes, config.ema_fast)
    ema_slow = _ema(closes, config.ema_slow)
    atr = _wilder_atr(candles, config.atr_period)
    atr_pct = _atr_percentile_series(atr, config.vol_lookback)
    labels = []
    for i in range(n):
        fast = ema_fast[i]
        slow = ema_slow[i]
        a = atr[i]
        pct = atr_pct[i]
        if fast is None or slow is None or a is None:
            labels.append(RegimeLabel(i, RANGING, fast, slow, a, pct))
            continue
        slope_norm = (fast - slow) / max(a, 1e-9)
        is_trending = abs(slope_norm) > config.trend_slope_threshold
        if pct is not None and pct <= config.vol_low_percentile:
            labels.append(RegimeLabel(i, LOW_VOL, fast, slow, a, pct))
        elif is_trending:
            regime = TRENDING_UP if slope_norm > 0 else TRENDING_DOWN
            labels.append(RegimeLabel(i, regime, fast, slow, a, pct))
        elif pct is not None and pct >= config.vol_high_percentile:
            labels.append(RegimeLabel(i, HIGH_VOL, fast, slow, a, pct))
        else:
            labels.append(RegimeLabel(i, RANGING, fast, slow, a, pct))
    return labels

def regime_distribution(labels):
    counts = {r: 0 for r in ALL_REGIMES}
    for lb in labels:
        counts[lb.regime] = counts.get(lb.regime, 0) + 1
    return counts


def regime_at(labels, index):
    if 0 <= index < len(labels):
        return labels[index].regime
    return None


def regime_breakdown(labels, trade_entry_indices, trade_pnls):
    result = {r: {"count": 0, "wins": 0, "total_pnl": 0.0} for r in ALL_REGIMES}
    for idx, pnl in zip(trade_entry_indices, trade_pnls, strict=True):
        regime = regime_at(labels, idx)
        if regime is None:
            continue
        bucket = result.setdefault(regime, {"count": 0, "wins": 0, "total_pnl": 0.0})
        bucket["count"] += 1
        bucket["total_pnl"] += float(pnl)
        if pnl > 0:
            bucket["wins"] += 1
    for bucket in result.values():
        n = bucket["count"]
        bucket["win_rate"] = (bucket["wins"] / n) if n else None
        bucket["avg_pnl"] = (bucket["total_pnl"] / n) if n else None
    return result
