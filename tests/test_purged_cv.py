"""Purged K-Fold with embargo — tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.research.purged_cv import (
    Fold,
    assert_disjoint,
    coverage_summary,
    purged_kfold_indices,
)


class PurgedKFoldTests(unittest.TestCase):
    def test_fold_count(self):
        folds = purged_kfold_indices(100, n_splits=5, purge_bars=2, embargo_bars=2)
        self.assertEqual(len(folds), 5)

    def test_fold_ids_sequential(self):
        folds = purged_kfold_indices(100, n_splits=5, purge_bars=2, embargo_bars=2)
        self.assertEqual([f.fold_id for f in folds], [0, 1, 2, 3, 4])

    def test_test_indices_partition(self):
        folds = purged_kfold_indices(100, n_splits=5, purge_bars=2, embargo_bars=2)
        all_test = []
        for f in folds:
            all_test.extend(f.test_indices)
        self.assertEqual(sorted(all_test), list(range(100)))

    def test_train_test_disjoint(self):
        folds = purged_kfold_indices(100, n_splits=5, purge_bars=2, embargo_bars=2)
        assert_disjoint(folds)

    def test_purge_removes_bars_after_test(self):
        folds = purged_kfold_indices(100, n_splits=5, purge_bars=5, embargo_bars=0)
        for f in folds:
            last_test = f.test_indices[-1]
            train_set = set(f.train_indices)
            # The 5 bars immediately after last_test must NOT be in train
            for offset in range(1, 6):
                idx = last_test + offset
                if idx < 100:
                    self.assertNotIn(idx, train_set,
                                     f"Fold {f.fold_id}: bar {idx} should be purged")

    def test_embargo_removes_bars_after_purge(self):
        folds = purged_kfold_indices(100, n_splits=5, purge_bars=5, embargo_bars=5)
        for f in folds:
            last_test = f.test_indices[-1]
            train_set = set(f.train_indices)
            # The 5 embargo bars (test_end + purge + 1..embargo) must not be in train
            embargo_start = last_test + 1 + 5
            for offset in range(0, 5):
                idx = embargo_start + offset
                if idx < 100:
                    self.assertNotIn(idx, train_set,
                                     f"Fold {f.fold_id}: bar {idx} should be embargoed")

    def test_purge_before_test_removes_prior_bars(self):
        folds = purged_kfold_indices(100, n_splits=5, purge_bars=3, embargo_bars=0)
        for f in folds:
            if f.fold_id == 0:
                continue
            first_test = f.test_indices[0]
            train_set = set(f.train_indices)
            # The 3 bars before first_test must not be in train
            for offset in range(1, 4):
                idx = first_test - offset
                if idx >= 0:
                    self.assertNotIn(idx, train_set,
                                     f"Fold {f.fold_id}: bar {idx} (before test) should be purged")

    def test_zero_purge_zero_embargo(self):
        folds = purged_kfold_indices(100, n_splits=5, purge_bars=0, embargo_bars=0)
        # With no purge/embargo, train is everything except test
        for f in folds:
            self.assertEqual(f.train_size + f.test_size, 100)

    def test_validation_error_small_n(self):
        with self.assertRaises(ValueError):
            purged_kfold_indices(5, n_splits=5, purge_bars=0, embargo_bars=0)

    def test_validation_error_negative_purge(self):
        with self.assertRaises(ValueError):
            purged_kfold_indices(100, n_splits=5, purge_bars=-1, embargo_bars=0)

    def test_validation_error_single_split(self):
        with self.assertRaises(ValueError):
            purged_kfold_indices(100, n_splits=1)


class CoverageSummaryTests(unittest.TestCase):
    def test_summary_fields(self):
        folds = purged_kfold_indices(100, n_splits=5, purge_bars=2, embargo_bars=2)
        summary = coverage_summary(folds, 100)
        self.assertEqual(summary["n_samples"], 100)
        self.assertGreater(summary["test_coverage"], 0.9)  # all tests used
        self.assertLessEqual(summary["test_coverage"], 1.0)
        self.assertGreaterEqual(summary["dropped_by_purge_embargo"], 0)


class FoldDataclassTests(unittest.TestCase):
    def test_fold_properties(self):
        f = Fold(fold_id=0, train_indices=(1, 2, 3), test_indices=(4, 5))
        self.assertEqual(f.train_size, 3)
        self.assertEqual(f.test_size, 2)


class IntegrationWithBacktestProtocolTests(unittest.TestCase):
    def test_folds_usable_with_segment_range(self):
        from fxars.research.protocol import SegmentRange
        folds = purged_kfold_indices(500, n_splits=5, purge_bars=10, embargo_bars=10)
        for f in folds:
            if not f.train_indices or not f.test_indices:
                continue
            train_range = SegmentRange("TRAIN", min(f.train_indices), max(f.train_indices) + 1)
            test_range = SegmentRange("TEST", min(f.test_indices), max(f.test_indices) + 1)
            # Sanity: test range is contiguous and non-empty
            self.assertGreater(test_range.size, 0)
            self.assertGreaterEqual(train_range.start, 0)


if __name__ == "__main__":
    unittest.main()
