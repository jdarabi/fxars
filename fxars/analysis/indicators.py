"""اندیکاتورهای قطعی و علّی (فقط گذشته).

همه توابع خروجی هم‌طول ورودی با None در دوره Warm-up برمی‌گردانند تا استفاده از
داده آینده به‌صورت ساختاری دشوار شود.
"""

from __future__ import annotations

from typing import Sequence

Number = float | None


def sma(values: Sequence[float], period: int) -> list[Number]:
    out: list[Number] = [None] * len(values)
    if period <= 0:
        return out
    window = 0.0
    for index, value in enumerate(values):
        window += value
        if index >= period:
            window -= values[index - period]
        if index >= period - 1:
            out[index] = window / period
    return out


def ema(values: Sequence[float], period: int) -> list[Number]:
    out: list[Number] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    multiplier = 2.0 / (period + 1.0)
    previous = seed
    for index in range(period, len(values)):
        previous = (values[index] - previous) * multiplier + previous
        out[index] = previous
    return out


def rsi(values: Sequence[float], period: int = 14) -> list[Number]:
    out: list[Number] = [None] * len(values)
    if len(values) <= period or period <= 0:
        return out
    gains = 0.0
    losses = 0.0
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[index] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
    ranges: list[float] = []
    for index in range(len(highs)):
        if index == 0:
            ranges.append(highs[0] - lows[0])
        else:
            ranges.append(max(highs[index] - lows[index], abs(highs[index] - closes[index - 1]),
                              abs(lows[index] - closes[index - 1])))
    return ranges


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> list[Number]:
    ranges = true_range(highs, lows, closes)
    out: list[Number] = [None] * len(ranges)
    if len(ranges) < period or period <= 0:
        return out
    initial = sum(ranges[:period]) / period
    out[period - 1] = initial
    previous = initial
    for index in range(period, len(ranges)):
        previous = (previous * (period - 1) + ranges[index]) / period
        out[index] = previous
    return out


def roc(values: Sequence[float], period: int = 10) -> list[Number]:
    out: list[Number] = [None] * len(values)
    if period <= 0:
        return out
    for index in range(period, len(values)):
        base = values[index - period]
        if base != 0:
            out[index] = (values[index] - base) / base
    return out


def rolling_std(values: Sequence[float], period: int) -> list[Number]:
    out: list[Number] = [None] * len(values)
    if period <= 1:
        return out
    for index in range(period - 1, len(values)):
        window = values[index - period + 1:index + 1]
        mean = sum(window) / period
        variance = sum((item - mean) ** 2 for item in window) / (period - 1)
        out[index] = variance ** 0.5
    return out


def returns(values: Sequence[float], period: int = 1) -> list[Number]:
    out: list[Number] = [None] * len(values)
    for index in range(period, len(values)):
        base = values[index - period]
        if base != 0:
            out[index] = (values[index] - base) / base
    return out


def percentile_rank_series(values: Sequence[float], window: int) -> list[Number]:
    """رتبه صدکی مقدار جاری در پنجره گذشته (شامل خودش)."""
    out: list[Number] = [None] * len(values)
    for index in range(len(values)):
        start = max(0, index - window + 1)
        sample = values[start:index + 1]
        if len(sample) < max(10, window // 3):
            continue
        current = values[index]
        below = sum(1 for item in sample if item <= current)
        out[index] = 100.0 * below / len(sample)
    return out


def last_valid(series: Sequence[Number]) -> float | None:
    for value in reversed(series):
        if value is not None:
            return float(value)
    return None


def value_at(series: Sequence[Number], index: int) -> float | None:
    if index < 0 or index >= len(series):
        return None
    return series[index]
