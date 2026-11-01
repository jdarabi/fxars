"""ابزارهای عددی: Decimal برای پول/قیمت/حجم، توابع آماری پایه."""

from __future__ import annotations

import math
import statistics
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation, getcontext
from typing import Iterable, Sequence

# دقت بالاتر از نیاز بازار برای جلوگیری از خطای گردکردن زنجیره‌ای
getcontext().prec = 34

D = Decimal
ZERO = Decimal("0")
ONE = Decimal("1")


def to_decimal(value: object, *, field: str = "value") -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError(f"{field} باید عدد باشد، نه boolean")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field} باید متناهی باشد")
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            raise ValueError(f"{field} خالی است")
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"{field} عدد معتبر نیست: {value!r}") from exc
        if not result.is_finite():
            raise ValueError(f"{field} باید متناهی باشد")
        return result
    raise ValueError(f"{field} نوع نامعتبر دارد: {type(value).__name__}")


def quantize(value: Decimal | int | float | str, digits: int, *, rounding: str = ROUND_HALF_UP) -> Decimal:
    quant = Decimal(1).scaleb(-digits)
    return to_decimal(value).quantize(quant, rounding=rounding)


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """گرد کردن رو به پایین به مضرب مجاز (برای حجم)."""
    if step <= 0:
        raise ValueError("step باید مثبت باشد")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0 or not math.isfinite(denominator):
        return default
    result = numerator / denominator
    return result if math.isfinite(result) else default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def stdev(values: Sequence[float], *, sample: bool = True) -> float:
    if len(values) < (2 if sample else 1):
        return 0.0
    return statistics.stdev(values) if sample else statistics.pstdev(values)


def percentile(values: Sequence[float], pct: float) -> float:
    """صدک با درون‌یابی خطی؛ pct در بازه ۰..۱۰۰."""
    data = sorted(values)
    if not data:
        return 0.0
    if len(data) == 1:
        return data[0]
    rank = (len(data) - 1) * clamp(pct, 0.0, 100.0) / 100.0
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return data[low]
    return data[low] + (data[high] - data[low]) * (rank - low)


def zscore(value: float, values: Sequence[float]) -> float:
    if len(values) < 3:
        return 0.0
    mu = mean(values)
    sigma = stdev(values)
    if sigma == 0:
        return 0.0
    return clamp((value - mu) / sigma, -6.0, 6.0)


def correlation(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    xs2, ys2 = xs[-n:], ys[-n:]
    mx, my = mean(xs2), mean(ys2)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs2, ys2)) / (n - 1)
    sx, sy = stdev(xs2), stdev(ys2)
    return clamp(safe_div(cov, sx * sy), -1.0, 1.0)


def normal_cdf(value: float) -> float:
    return statistics.NormalDist().cdf(value)


def normal_ppf(prob: float) -> float:
    p = clamp(prob, 1e-12, 1 - 1e-12)
    return statistics.NormalDist().inv_cdf(p)


def annualization_factor(timeframe: str) -> float:
    from fxars.core.timeutil import TIMEFRAME_MINUTES

    minutes = TIMEFRAME_MINUTES.get(timeframe, 60)
    if minutes >= 10080:
        return 52.0
    if minutes >= 1440:
        return 252.0
    bars_per_day = 1440 / minutes
    return bars_per_day * 252.0


def fmt_decimal(value: Decimal, digits: int | None = None) -> str:
    if digits is None:
        return format(value, "f")
    return format(quantize(value, digits), f".{digits}f")


def pips_to_price(pips: Decimal | float | str, pip_size: Decimal) -> Decimal:
    return to_decimal(pips, field="pips") * pip_size


def sum_decimals(values: Iterable[Decimal]) -> Decimal:
    total = ZERO
    for value in values:
        total += value
    return total
