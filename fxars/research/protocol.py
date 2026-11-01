"""پروتکل اعتبارسنجی: Train/Validation/Locked Test، Embargo و Walk-forward."""

from __future__ import annotations

from dataclasses import dataclass

from fxars.core.errors import ValidationError
from fxars.domain.enums import BacktestSegment


@dataclass(frozen=True)
class SegmentRange:
    name: BacktestSegment
    start: int
    end: int  # exclusive

    @property
    def size(self) -> int:
        return max(0, self.end - self.start)


@dataclass(frozen=True)
class ValidationSplit:
    train: SegmentRange
    validation: SegmentRange
    locked_test: SegmentRange
    embargo_bars: int
    total_bars: int

    def to_dict(self) -> dict:
        return {
            "train": {"start": self.train.start, "end": self.train.end, "size": self.train.size},
            "validation": {"start": self.validation.start, "end": self.validation.end, "size": self.validation.size},
            "locked_test": {"start": self.locked_test.start, "end": self.locked_test.end, "size": self.locked_test.size},
            "embargo_bars": self.embargo_bars,
            "total_bars": self.total_bars,
        }


def split_segments(total_bars: int, *, train_fraction: float = 0.6, validation_fraction: float = 0.2,
                   embargo_bars: int = 5) -> ValidationSplit:
    if total_bars < 50:
        raise ValidationError("برای تقسیم اعتبارسنجی حداقل ۵۰ کندل لازم است.", details={"bars": total_bars})
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValidationError("نسبت‌های تقسیم باید بین ۰ و ۱ باشند.")
    if train_fraction + validation_fraction >= 0.95:
        raise ValidationError("باید حداقل ۵٪ داده برای Locked Test باقی بماند.")
    if embargo_bars < 0:
        raise ValidationError("embargo نمی‌تواند منفی باشد.")

    train_end = int(total_bars * train_fraction)
    validation_end = int(total_bars * (train_fraction + validation_fraction))
    validation_start = train_end + embargo_bars
    locked_start = validation_end + embargo_bars
    if locked_start >= total_bars - 10:
        raise ValidationError("بازه Locked Test پس از Embargo بسیار کوچک است.")
    return ValidationSplit(
        train=SegmentRange(BacktestSegment.TRAIN, 0, train_end),
        validation=SegmentRange(BacktestSegment.VALIDATION, validation_start, validation_end),
        locked_test=SegmentRange(BacktestSegment.LOCKED_TEST, locked_start, total_bars),
        embargo_bars=embargo_bars,
        total_bars=total_bars,
    )


def segment_range(split: ValidationSplit, segment: BacktestSegment) -> SegmentRange:
    if segment is BacktestSegment.TRAIN:
        return split.train
    if segment is BacktestSegment.VALIDATION:
        return split.validation
    if segment is BacktestSegment.LOCKED_TEST:
        return split.locked_test
    return SegmentRange(BacktestSegment.ALL, 0, split.total_bars)


def assert_disjoint(split: ValidationSplit) -> None:
    ranges = [split.train, split.validation, split.locked_test]
    for index, first in enumerate(ranges):
        for second in ranges[index + 1:]:
            if first.start < second.end and second.start < first.end:
                raise ValidationError(
                    "بازه‌های Train/Validation/Locked Test هم‌پوشانی دارند.",
                    details={"first": first.name.value, "second": second.name.value},
                )


@dataclass(frozen=True)
class WalkForwardWindow:
    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int

    def to_dict(self) -> dict:
        return {
            "fold": self.fold, "train_start": self.train_start, "train_end": self.train_end,
            "test_start": self.test_start, "test_end": self.test_end,
        }


def walk_forward_windows(total_bars: int, *, train_bars: int, test_bars: int, step_bars: int,
                         min_train: int = 200) -> list[WalkForwardWindow]:
    if train_bars < min_train or test_bars < 20 or step_bars < 20:
        raise ValidationError("پارامترهای Walk-forward کوچک‌تر از حداقل مجاز هستند.")
    windows: list[WalkForwardWindow] = []
    start = 0
    fold = 1
    while start + train_bars + test_bars <= total_bars:
        windows.append(
            WalkForwardWindow(
                fold=fold,
                train_start=start,
                train_end=start + train_bars,
                test_start=start + train_bars,
                test_end=start + train_bars + test_bars,
            )
        )
        start += step_bars
        fold += 1
    return windows
