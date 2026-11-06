"""ML pipeline: Triple Barrier labels + Purged K-Fold, end-to-end."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from fxars.domain.models import Candle
from fxars.research.labeling import (
    TripleBarrierConfig,
    TripleBarrierLabel,
    label_statistics,
    triple_barrier_labels,
)
from fxars.research.purged_cv import (
    Fold,
    assert_disjoint,
    coverage_summary,
    purged_kfold_indices,
)


@dataclass
class MLPipelineConfig:
    """Full configuration for the label + CV pipeline."""
    labeling: TripleBarrierConfig = field(default_factory=TripleBarrierConfig)
    n_splits: int = 5
    purge_bars: int = 10
    embargo_bars: int = 10


@dataclass
class MLPipelineResult:
    """Full pipeline output."""
    labels: list[TripleBarrierLabel]
    folds: list[Fold]
    label_stats: dict[str, Any]
    coverage: dict[str, Any]
    X: list[list[float]]
    y: list[int]
    indices: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label_stats": self.label_stats,
            "coverage": self.coverage,
            "n_labels": len(self.labels),
            "n_folds": len(self.folds),
            "n_samples": len(self.X),
            "n_features": len(self.X[0]) if self.X else 0,
            "folds": [
                {
                    "fold_id": f.fold_id,
                    "train_size": f.train_size,
                    "test_size": f.test_size,
                }
                for f in self.folds
            ],
        }


def _default_feature_fn(candles: Sequence[Candle], index: int) -> list[float] | None:
    """Causal baseline features: close, high-low, body, upper/lower wick."""
    if index < 0 or index >= len(candles):
        return None
    c = candles[index]
    body = float(abs(c.close - c.open))
    rng = float(c.high - c.low)
    if rng <= 0:
        return None
    return [
        float(c.close),
        rng,
        body / rng,
        float(c.upper_wick),
        float(c.lower_wick),
    ]


def run_ml_pipeline(
    candles: Sequence[Candle],
    config: MLPipelineConfig | None = None,
    *,
    feature_fn: Callable[[Sequence[Candle], int], list[float] | None] | None = None,
) -> MLPipelineResult:
    """Run Triple Barrier labeling and Purged K-Fold split on the same dataset.

    The folds are computed over the *label index space* (i.e., the sequence of
    entries that received a label), not over raw candle indices. This is the
    correct behavior: folds must not leak across barrier horizons.
    """
    config = config or MLPipelineConfig()
    feature_fn = feature_fn or _default_feature_fn

    labels = triple_barrier_labels(candles, config.labeling)
    if not labels:
        return MLPipelineResult(
            labels=[], folds=[], label_stats=label_statistics([]),
            coverage={"n_samples": 0}, X=[], y=[], indices=[],
        )

    # Build ML dataset first so folds map to actual training rows.
    X: list[list[float]] = []
    y: list[int] = []
    entry_indices: list[int] = []
    for lb in labels:
        feats = feature_fn(candles, lb.entry_index)
        if feats is None:
            continue
        X.append(list(feats))
        y.append(1 if lb.label > 0 else 0)
        entry_indices.append(lb.entry_index)

    n = len(X)
    folds: list[Fold] = []
    if n >= config.n_splits * 2:
        folds = purged_kfold_indices(
            n,
            n_splits=config.n_splits,
            purge_bars=config.purge_bars,
            embargo_bars=config.embargo_bars,
        )
        assert_disjoint(folds)

    return MLPipelineResult(
        labels=labels,
        folds=folds,
        label_stats=label_statistics(labels),
        coverage=coverage_summary(folds, n) if folds else {"n_samples": n},
        X=X,
        y=y,
        indices=entry_indices,
    )


def train_test_arrays(
    result: MLPipelineResult,
    fold: Fold,
) -> tuple[list[list[float]], list[int], list[list[float]], list[int]]:
    """Extract (X_train, y_train, X_test, y_test) for a single fold."""
    X_train = [result.X[i] for i in fold.train_indices]
    y_train = [result.y[i] for i in fold.train_indices]
    X_test = [result.X[i] for i in fold.test_indices]
    y_test = [result.y[i] for i in fold.test_indices]
    return X_train, y_train, X_test, y_test
