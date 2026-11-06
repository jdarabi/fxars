"""Calibration metrics and post-hoc calibration.

Covered by AC-09: no probability should be displayed without calibration.
This module provides:
  * Brier Score
  * LogLoss (with clipping)
  * Expected Calibration Error (ECE)
  * Reliability diagram data (and SVG renderer)
  * Temperature scaling (single-parameter calibration)
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from fxars.core.numerics import clamp, mean

# ---------------------------------------------------------------------------
# Basic metrics
# ---------------------------------------------------------------------------

def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    """Brier score: mean squared error between predicted prob and outcome.

    Lower is better. Range [0, 1]. Baseline (always predict base rate) has
    Brier = p*(1-p) where p is the base rate.
    """
    n = min(len(probabilities), len(outcomes))
    if n == 0:
        return 0.0
    total = 0.0
    for i in range(n):
        p = clamp(float(probabilities[i]), 0.0, 1.0)
        y = 1.0 if outcomes[i] else 0.0
        total += (p - y) ** 2
    return total / n


def log_loss(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    *,
    epsilon: float = 1e-15,
) -> float:
    """Binary cross-entropy, clipped for numerical stability."""
    n = min(len(probabilities), len(outcomes))
    if n == 0:
        return 0.0
    total = 0.0
    for i in range(n):
        p = clamp(float(probabilities[i]), epsilon, 1.0 - epsilon)
        y = 1.0 if outcomes[i] else 0.0
        total -= y * math.log(p) + (1.0 - y) * math.log(1.0 - p)
    return total / n


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_probability: float
    empirical_frequency: float

    def to_dict(self) -> dict:
        return {
            "lower": round(self.lower, 4),
            "upper": round(self.upper, 4),
            "count": self.count,
            "mean_probability": round(self.mean_probability, 4),
            "empirical_frequency": round(self.empirical_frequency, 4),
            "gap": round(self.mean_probability - self.empirical_frequency, 4),
        }


def bin_predictions(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    *,
    n_bins: int = 10,
) -> list[CalibrationBin]:
    """Group predictions into equal-width bins and compute per-bin statistics."""
    n = min(len(probabilities), len(outcomes))
    if n == 0 or n_bins < 1:
        return []
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for i in range(n):
        p = clamp(float(probabilities[i]), 0.0, 1.0)
        y = 1 if outcomes[i] else 0
        # Map [0,1] to [0, n_bins]; keep max in last bin.
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, y))
    result: list[CalibrationBin] = []
    width = 1.0 / n_bins
    for index, bucket in enumerate(bins):
        lower = index * width
        upper = (index + 1) * width
        if not bucket:
            result.append(CalibrationBin(lower, upper, 0, 0.0, 0.0))
            continue
        probs = [p for p, _ in bucket]
        ys = [y for _, y in bucket]
        result.append(CalibrationBin(
            lower=lower,
            upper=upper,
            count=len(bucket),
            mean_probability=mean(probs),
            empirical_frequency=mean([float(y) for y in ys]),
        ))
    return result


def expected_calibration_error(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    *,
    n_bins: int = 10,
) -> float:
    """ECE = sum over bins of (bin_count / n) * |mean_prob - empirical_freq|."""
    n = min(len(probabilities), len(outcomes))
    if n == 0:
        return 0.0
    bins = bin_predictions(probabilities, outcomes, n_bins=n_bins)
    total = 0.0
    for item in bins:
        if item.count == 0:
            continue
        total += (item.count / n) * abs(item.mean_probability - item.empirical_frequency)
    return total


def maximum_calibration_error(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    *,
    n_bins: int = 10,
) -> float:
    """MCE = max over bins of |mean_prob - empirical_freq| (only non-empty bins)."""
    bins = bin_predictions(probabilities, outcomes, n_bins=n_bins)
    gaps = [abs(item.mean_probability - item.empirical_frequency) for item in bins if item.count > 0]
    return max(gaps) if gaps else 0.0


# ---------------------------------------------------------------------------
# Temperature scaling
# ---------------------------------------------------------------------------

@dataclass
class TemperatureScaling:
    """Post-hoc calibration: p' = sigmoid(logit(p) / T).

    T > 1 softens (over-confident model), T < 1 sharpens (under-confident).
    Fitted by grid search over T; simple and monotonic (preserves ranking).
    """
    temperature: float = 1.0

    @staticmethod
    def _logit(p: float, epsilon: float = 1e-9) -> float:
        p = clamp(p, epsilon, 1.0 - epsilon)
        return math.log(p / (1.0 - p))

    @staticmethod
    def _sigmoid(x: float) -> float:
        if x >= 0:
            z = math.exp(-x)
            return 1.0 / (1.0 + z)
        z = math.exp(x)
        return z / (1.0 + z)

    def transform(self, probability: float) -> float:
        return self._sigmoid(self._logit(probability) / self.temperature)

    def transform_all(self, probabilities: Sequence[float]) -> list[float]:
        return [self.transform(p) for p in probabilities]

    def fit(
        self,
        probabilities: Sequence[float],
        outcomes: Sequence[int],
        *,
        grid: Sequence[float] = (0.5, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 2.0, 3.0),
    ) -> TemperatureScaling:
        """Choose T minimizing LogLoss on the given set."""
        best_loss = float("inf")
        best_t = 1.0
        for t in grid:
            if t <= 0:
                continue
            candidate = TemperatureScaling(temperature=float(t))
            calibrated = candidate.transform_all(probabilities)
            loss = log_loss(calibrated, outcomes)
            if loss < best_loss:
                best_loss = loss
                best_t = float(t)
        self.temperature = best_t
        return self


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class CalibrationReport:
    n: int
    brier: float
    log_loss: float
    ece: float
    mce: float
    n_bins: int
    bins: list[CalibrationBin]
    temperature: float | None = None
    brier_after: float | None = None
    log_loss_after: float | None = None
    ece_after: float | None = None

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "brier": round(self.brier, 6),
            "log_loss": round(self.log_loss, 6),
            "ece": round(self.ece, 6),
            "mce": round(self.mce, 6),
            "n_bins": self.n_bins,
            "bins": [b.to_dict() for b in self.bins],
            "temperature": self.temperature,
            "after_calibration": (
                None if self.temperature is None else {
                    "brier": round(self.brier_after, 6) if self.brier_after is not None else None,
                    "log_loss": round(self.log_loss_after, 6) if self.log_loss_after is not None else None,
                    "ece": round(self.ece_after, 6) if self.ece_after is not None else None,
                }
            ),
        }

    @property
    def is_acceptable(self) -> bool:
        """Convention: ECE < 0.10 is acceptable for display (AC-09)."""
        return self.ece < 0.10


def calibration_report(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    *,
    n_bins: int = 10,
    apply_temperature: bool = True,
) -> CalibrationReport:
    """Build a full calibration report; optionally include post-hoc T-scaling."""
    n = min(len(probabilities), len(outcomes))
    if n == 0:
        return CalibrationReport(
            n=0, brier=0.0, log_loss=0.0, ece=0.0, mce=0.0,
            n_bins=n_bins, bins=[],
        )
    raw_brier = brier_score(probabilities, outcomes)
    raw_ll = log_loss(probabilities, outcomes)
    raw_ece = expected_calibration_error(probabilities, outcomes, n_bins=n_bins)
    raw_mce = maximum_calibration_error(probabilities, outcomes, n_bins=n_bins)
    bins = bin_predictions(probabilities, outcomes, n_bins=n_bins)

    temperature = None
    brier_after = log_loss_after = ece_after = None
    if apply_temperature and n >= 20:
        scaler = TemperatureScaling().fit(probabilities, outcomes)
        calibrated = scaler.transform_all(probabilities)
        temperature = scaler.temperature
        brier_after = brier_score(calibrated, outcomes)
        log_loss_after = log_loss(calibrated, outcomes)
        ece_after = expected_calibration_error(calibrated, outcomes, n_bins=n_bins)

    return CalibrationReport(
        n=n, brier=raw_brier, log_loss=raw_ll, ece=raw_ece, mce=raw_mce,
        n_bins=n_bins, bins=bins,
        temperature=temperature, brier_after=brier_after,
        log_loss_after=log_loss_after, ece_after=ece_after,
    )


# ---------------------------------------------------------------------------
# SVG reliability diagram
# ---------------------------------------------------------------------------

def reliability_diagram_svg(
    report: CalibrationReport,
    *,
    width: int = 400,
    height: int = 400,
) -> str:
    """Render a reliability diagram as inline SVG."""
    if report.n == 0 or not report.bins:
        return "<p>داده کافی برای نمودار کالیبراسیون موجود نیست.</p>"
    pad = 40
    plot_w = width - pad * 2
    plot_h = height - pad * 2

    def to_xy(p: float, y: float) -> tuple[float, float]:
        x = pad + p * plot_w
        py = pad + (1.0 - y) * plot_h
        return x, py

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" xmlns="http://www.w3.org/2000/svg">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#0b1220"/>',
        # Grid + diagonal
        f'<line x1="{pad}" y1="{pad + plot_h}" x2="{pad + plot_w}" y2="{pad + plot_h}" stroke="#475569" stroke-width="1"/>',
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{pad + plot_h}" stroke="#475569" stroke-width="1"/>',
        f'<line x1="{pad}" y1="{pad + plot_h}" x2="{pad + plot_w}" y2="{pad}" stroke="#64748b" stroke-dasharray="4,4"/>',
    ]
    # Bins as bars
    for item in report.bins:
        if item.count == 0:
            continue
        x1, y1 = to_xy(item.mean_probability, item.empirical_frequency)
        _, y0 = to_xy(item.mean_probability, 0.0)
        bar_w = max(3.0, plot_w / report.n_bins * 0.6)
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" '
            f'stroke="#38bdf8" stroke-width="{bar_w:.1f}"/>'
        )
        parts.append(
            f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="3" fill="#f59e0b"/>'
        )
    # Axis labels
    parts.append(f'<text x="{pad}" y="{height - 8}" fill="#94a3b8" font-size="11">0</text>')
    parts.append(f'<text x="{pad + plot_w - 8}" y="{height - 8}" fill="#94a3b8" font-size="11">1</text>')
    parts.append(f'<text x="4" y="{pad}" fill="#94a3b8" font-size="11">1</text>')
    parts.append(f'<text x="4" y="{pad + plot_h}" fill="#94a3b8" font-size="11">0</text>')
    # Summary
    summary = f"ECE={report.ece:.3f}  Brier={report.brier:.3f}  LogLoss={report.log_loss:.3f}"
    parts.append(f'<text x="{pad}" y="{pad - 12}" fill="#93c5fd" font-size="12">{summary}</text>')
    parts.append("</svg>")
    return "".join(parts)
