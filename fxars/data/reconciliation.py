"""گزارش تطبیق صریح کندل‌ها: تعداد و زمان مورد انتظار در برابر داده ذخیره‌شده."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from fxars.core.timeutil import ensure_utc, format_ts, utcnow
from fxars.domain.enums import Timeframe
from fxars.domain.models import Candle
from fxars.instruments.calendar import GRID_TOLERANCE, TradingCalendar

MAX_SAMPLES = 10


@dataclass(frozen=True)
class CandleMatchReport:
    instrument_id: str
    timeframe: str
    source_id: str
    checked_at: datetime
    first_present_at: datetime | None
    latest_present_at: datetime | None
    latest_expected_at: datetime | None
    expected: int
    present: int
    matched: int
    missing: int
    extra: int
    duplicates: int
    missing_times: tuple[datetime, ...] = ()
    extra_times: tuple[datetime, ...] = ()

    @property
    def ok(self) -> bool:
        return self.missing == 0 and self.duplicates == 0

    def to_dict(self, *, max_samples: int = MAX_SAMPLES) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "source_id": self.source_id,
            "checked_at": format_ts(self.checked_at),
            "first_present_at": format_ts(self.first_present_at) if self.first_present_at else None,
            "latest_present_at": format_ts(self.latest_present_at) if self.latest_present_at else None,
            "latest_expected_at": format_ts(self.latest_expected_at) if self.latest_expected_at else None,
            "expected": self.expected,
            "present": self.present,
            "matched": self.matched,
            "missing": self.missing,
            "extra": self.extra,
            "duplicates": self.duplicates,
            "missing_samples": [format_ts(moment) for moment in self.missing_times[:max_samples]],
            "extra_samples": [format_ts(moment) for moment in self.extra_times[:max_samples]],
            "ok": self.ok,
        }


def match_candles(
    candles: Sequence[Candle],
    *,
    instrument_id: str,
    timeframe: str | Timeframe,
    source_id: str,
    calendar: TradingCalendar,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> CandleMatchReport:
    """کندل‌های مورد انتظار تقویم را با کندل‌های موجود مقایسه می‌کند.

    بازه مقایسه: از شبکهٔ کندلِ اولین رکورد ذخیره‌شده تا آخرین رکورد (یا start/end صریح).
    `latest_expected_at` آخرین کندل بستهٔ مورد انتظار تا `now` است، مستقل از بازه داده.
    """
    tf = Timeframe.parse(timeframe)
    checked_at = now or utcnow()
    window_start = ensure_utc(start) if start is not None else None
    window_end = ensure_utc(end) if end is not None else None

    window = [
        candle for candle in candles
        if (window_start is None or candle.open_time >= window_start)
        and (window_end is None or candle.open_time <= window_end)
    ]
    counts = Counter(candle.open_time for candle in window)
    present_times = sorted(counts)
    duplicates = sum(count - 1 for count in counts.values())

    if window_start is None and present_times:
        window_start = present_times[0]
    if window_end is None and present_times:
        window_end = present_times[-1]

    expected_times: list[datetime] = []
    if window_start is not None and window_end is not None and window_start <= window_end:
        expected_times = calendar.expected_bar_times(
            calendar.bar_floor(window_start, tf), window_end, tf, instrument_id=instrument_id,
        )

    tolerance = GRID_TOLERANCE if tf.minutes >= 240 else timedelta(0)
    matched_present, missing_times = _match(expected_times, present_times, tolerance)
    extra_times = tuple(moment for moment in present_times if moment not in matched_present)

    return CandleMatchReport(
        instrument_id=instrument_id,
        timeframe=tf.value,
        source_id=source_id,
        checked_at=checked_at,
        first_present_at=present_times[0] if present_times else None,
        latest_present_at=present_times[-1] if present_times else None,
        latest_expected_at=calendar.last_closed_bar_time(checked_at, tf, instrument_id=instrument_id),
        expected=len(expected_times),
        present=len(present_times),
        matched=len(matched_present),
        missing=len(missing_times),
        extra=len(extra_times),
        duplicates=duplicates,
        missing_times=tuple(missing_times),
        extra_times=extra_times,
    )


def _match(
    expected: list[datetime], present: list[datetime], tolerance: timedelta,
) -> tuple[set[datetime], list[datetime]]:
    matched: set[datetime] = set()
    missing: list[datetime] = []
    for moment in expected:
        index = bisect_left(present, moment)
        candidate: datetime | None = None
        for offset in (0, -1, 1):
            position = index + offset
            if 0 <= position < len(present):
                value = present[position]
                if value not in matched and abs(value - moment) <= tolerance:
                    candidate = value
                    break
        if candidate is None:
            missing.append(moment)
        else:
            matched.add(candidate)
    return matched, missing
