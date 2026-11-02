"""کنترل بیش‌برازش: Deflated Sharpe Ratio و Probability of Backtest Overfitting."""

from __future__ import annotations

import math
from itertools import combinations
from typing import Sequence

from fxars.core.numerics import mean, normal_cdf, normal_ppf, safe_div, stdev

EULER_GAMMA = 0.5772156649015329


def _moments(values: Sequence[float]) -> tuple[float, float, float]:
    n = len(values)
    if n < 3:
        return 0.0, 3.0, 0.0
    mu = mean(values)
    variance = sum((value - mu) ** 2 for value in values) / n
    if variance == 0:
        return 0.0, 3.0, 0.0
    m3 = sum((value - mu) ** 3 for value in values) / n
    m4 = sum((value - mu) ** 4 for value in values) / n
    skew = m3 / variance ** 1.5
    kurtosis = m4 / variance ** 2
    return skew, kurtosis, variance


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    trials: int,
    periods_per_year: float = 1.0,
) -> dict[str, float | int | None]:
    """DSR مطابق Bailey & López de Prado.

    FIX-P1-4: ``sharpe`` با ``periods_per_year`` سالانهسازی میشود تا با
    ``compute_metrics`` همخوان باشد.
    """
    n = len(returns)
    if n < 5 or trials < 1:
        return {"sharpe": 0.0, "sr0": 0.0, "dsr": None, "trials": trials, "observations": n}

    sigma = stdev(returns)
    if sigma <= 0:
        return {
            "sharpe": 0.0, "sr0": 0.0, "dsr": None,
            "trials": trials, "observations": n,
            "skew": 0.0, "kurtosis": 3.0, "periods_per_year": periods_per_year,
        }

    per_period_sr = mean(returns) / sigma
    sr = per_period_sr * math.sqrt(periods_per_year)
    skew, kurtosis, _ = _moments(returns)

    if n <= 1:
        return {
            "sharpe": round(sr, 6), "sr0": 0.0, "dsr": None,
            "trials": trials, "observations": n,
            "periods_per_year": periods_per_year,
        }

    variance_sr = max(
        (1 - skew * per_period_sr + (kurtosis - 1) / 4 * per_period_sr * per_period_sr) / (n - 1),
        1e-12,
    )
    std_sr = math.sqrt(variance_sr)
    if trials == 1:
        sr0 = 0.0
    else:
        sr0 = std_sr * (
            (1 - EULER_GAMMA) * normal_ppf(1 - 1.0 / trials)
            + EULER_GAMMA * normal_ppf(1 - 1.0 / (trials * math.e))
        )

    denominator = math.sqrt(max(
        1 - skew * per_period_sr + (kurtosis - 1) / 4 * per_period_sr * per_period_sr,
        1e-12,
    ))
    statistic = (per_period_sr - sr0) * math.sqrt(n - 1) / denominator

    return {
        "sharpe": round(sr, 6),
        "sr0": round(sr0, 6),
        "dsr": round(normal_cdf(statistic), 6),
        "trials": trials,
        "observations": n,
        "skew": round(skew, 6),
        "kurtosis": round(kurtosis, 6),
        "periods_per_year": periods_per_year,
    }


def probability_of_backtest_overfitting(
    returns_matrix: Sequence[Sequence[float]],
    *,
    blocks: int = 10,
) -> dict[str, object]:
    """CSCV: احتمال اینکه بهترین استراتژی در نمونه، در خارج نمونه بد باشد."""
    if not returns_matrix:
        return {"pbo": None, "splits": 0, "strategies": 0}
    lengths = {len(row) for row in returns_matrix}
    if len(lengths) != 1:
        raise ValueError("همه سری‌های بازده باید هم‌طول باشند.")
    total = lengths.pop()
    strategies = len(returns_matrix)
    if total < blocks * 2 or strategies < 2:
        return {"pbo": None, "splits": 0, "strategies": strategies, "reason": "INSUFFICIENT_DATA"}

    block_size = total // blocks
    usable = block_size * blocks
    slices = [(index * block_size, (index + 1) * block_size) for index in range(blocks)]
    half = blocks // 2
    logits: list[float] = []
    is_best_counts: dict[int, int] = {}
    for combination in combinations(range(blocks), half):
        is_indices = [index for block in combination for index in range(*slices[block])]
        oos_indices = [index for block, span in enumerate(slices) if block not in combination for index in range(*span)]
        is_scores = [_score(row, is_indices) for row in returns_matrix]
        oos_scores = [_score(row, oos_indices) for row in returns_matrix]
        best = max(range(strategies), key=lambda index: is_scores[index])
        is_best_counts[best] = is_best_counts.get(best, 0) + 1
        rank = 1 + sum(1 for score in oos_scores if score > oos_scores[best])
        logit = math.log(rank / (strategies + 1 - rank))
        logits.append(logit)
    below = sum(1 for value in logits if value <= 0)
    pbo = below / len(logits) if logits else None
    return {
        "pbo": round(pbo, 6) if pbo is not None else None,
        "splits": len(logits),
        "strategies": strategies,
        "blocks": blocks,
        "median_logit": round(sorted(logits)[len(logits) // 2], 6) if logits else None,
        "worst_logit": round(min(logits), 6) if logits else None,
        "best_strategy_counts": {str(key): value for key, value in sorted(is_best_counts.items())},
    }


def _score(returns: Sequence[float], indices: Sequence[int]) -> float:
    sample = [returns[index] for index in indices]
    sigma = stdev(sample)
    if sigma == 0:
        return mean(sample)
    return mean(sample) / sigma * math.sqrt(len(sample))


def minimum_track_record_length(sharpe: float, *, target: float = 0.0, confidence: float = 0.95) -> float:
    """طول حداقلی نمونه برای اثبات معنی‌دار بودن SR (تقریب)."""
    if sharpe <= 0:
        return float("inf")
    z = normal_ppf(confidence)
    return 1 + (z / (sharpe - target)) ** 2
