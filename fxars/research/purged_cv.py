"""Purged K-Fold with embargo for time-series cross-validation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Fold:
    fold_id: int
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]

    @property
    def train_size(self) -> int:
        return len(self.train_indices)

    @property
    def test_size(self) -> int:
        return len(self.test_indices)


def purged_kfold_indices(
    n_samples: int,
    *,
    n_splits: int = 5,
    purge_bars: int = 5,
    embargo_bars: int = 5,
) -> list[Fold]:
    """Standard Purged K-Fold (López de Prado, AFML ch. 7).

    For each fold, remove from train:
      * ``purge_bars`` after each test block (prevents label leakage)
      * ``embargo_bars`` after each test block (prevents autocorrelation leakage)

    Args:
        n_samples: total number of observations (rows).
        n_splits: number of folds (>= 2).
        purge_bars: number of bars to drop AFTER each test block.
        embargo_bars: number of bars to drop AFTER the purged region.

    Returns:
        List of Fold objects, one per split, in chronological order.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    if purge_bars < 0 or embargo_bars < 0:
        raise ValueError("purge_bars and embargo_bars must be >= 0")
    if n_samples < n_splits * 2:
        raise ValueError(
            f"n_samples ({n_samples}) must be >= 2 * n_splits ({n_splits * 2})"
        )

    indices = list(range(n_samples))
    fold_size = n_samples // n_splits
    remainder = n_samples - fold_size * n_splits

    folds: list[Fold] = []
    cursor = 0
    for fold_id in range(n_splits):
        # Distribute remainder over early folds
        this_size = fold_size + (1 if fold_id < remainder else 0)
        test_start = cursor
        test_end = cursor + this_size

        purge_end = min(n_samples, test_end + purge_bars)
        embargo_end = min(n_samples, purge_end + embargo_bars)

        test_indices = tuple(indices[test_start:test_end])
        train_indices = tuple(
            indices[i] for i in indices
            if i < test_start
            or (i >= embargo_end)
            # Also drop the purge region to be symmetric on both sides of the
            # test block; some implementations only purge forward, but for
            # FX autocorrelation, both sides is safer.
        )
        # Additionally purge before test_start
        purge_before = max(0, test_start - purge_bars)
        train_indices = tuple(
            i for i in train_indices
            if i < purge_before or i >= embargo_end
        )

        folds.append(Fold(
            fold_id=fold_id,
            train_indices=train_indices,
            test_indices=test_indices,
        ))
        cursor = test_end

    return folds


def assert_disjoint(folds: Iterable[Fold]) -> None:
    """Verify no train/test index overlap within or across folds."""
    seen_train: set[int] = set()
    seen_test: set[int] = set()
    for fold in folds:
        train_set = set(fold.train_indices)
        test_set = set(fold.test_indices)
        overlap = train_set & test_set
        if overlap:
            raise AssertionError(
                f"Fold {fold.fold_id}: train/test overlap at indices {sorted(overlap)[:5]}"
            )
        if train_set & seen_train:
            # Cross-fold train overlap is allowed (that is the point of CV),
            # but test overlap is not.
            pass
        if test_set & seen_test:
            raise AssertionError(
                f"Fold {fold.fold_id}: test indices overlap with a previous fold"
            )
        seen_train |= train_set
        seen_test |= test_set


def coverage_summary(folds: Iterable[Fold], n_samples: int) -> dict:
    """Report what fraction of samples are used for train vs. test, and what
    fraction is dropped by purge + embargo."""
    all_test: set[int] = set()
    all_train_union: set[int] = set()
    all_used: set[int] = set()
    for fold in folds:
        all_test |= set(fold.test_indices)
        all_train_union |= set(fold.train_indices)
        all_used |= set(fold.train_indices)
        all_used |= set(fold.test_indices)
    dropped = n_samples - len(all_used)
    return {
        "n_samples": n_samples,
        "test_coverage": len(all_test) / n_samples if n_samples else 0.0,
        "train_union_coverage": len(all_train_union) / n_samples if n_samples else 0.0,
        "dropped_by_purge_embargo": dropped,
        "dropped_fraction": dropped / n_samples if n_samples else 0.0,
    }
