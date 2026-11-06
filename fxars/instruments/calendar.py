"""تقویم معاملاتی: سشن‌ها، DST، تعطیلات و کندل‌های مورد انتظار.

هدف: کیفیت داده و Freshness نباید در تعطیلات/تعطیلی بازار هشدار کاذب بدهد.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fxars.core.timeutil import ensure_utc, floor_to_timeframe
from fxars.domain.enums import SessionName, Timeframe


@dataclass(frozen=True)
class Session:
    name: SessionName
    timezone: str
    start: time
    end: time

    def contains(self, moment: datetime) -> bool:
        local = ensure_utc(moment).astimezone(ZoneInfo(self.timezone))
        if local.weekday() >= 5:
            return False
        current = local.time()
        if self.start <= self.end:
            return self.start <= current < self.end
        return current >= self.start or current < self.end


DEFAULT_SESSIONS = (
    Session(SessionName.SYDNEY, "Australia/Sydney", time(7, 0), time(16, 0)),
    Session(SessionName.TOKYO, "Asia/Tokyo", time(9, 0), time(18, 0)),
    Session(SessionName.LONDON, "Europe/London", time(8, 0), time(16, 30)),
    Session(SessionName.NEW_YORK, "America/New_York", time(8, 0), time(17, 0)),
)


class TradingCalendar:
    """تقویم فارکس ۲۴/۵ با پشتیبانی از تعطیلات پیکربندی‌شده."""

    def __init__(
        self,
        holidays: set[date] | None = None,
        *,
        sessions: tuple[Session, ...] = DEFAULT_SESSIONS,
        week_open_utc: time = time(21, 0),
        week_close_utc: time = time(21, 0),
    ) -> None:
        self.holidays = holidays or set()
        self.sessions = sessions
        self.week_open_utc = week_open_utc
        self.week_close_utc = week_close_utc

    # ---------------------------------------------------------------- وضعیت بازار
    def is_market_open(self, moment: datetime) -> bool:
        dt = ensure_utc(moment)
        if dt.date() in self.holidays:
            return False
        weekday = dt.weekday()  # Monday=0 ... Sunday=6
        if weekday == 5:
            return False
        if weekday == 6:  # Sunday
            return dt.time() >= self.week_open_utc
        if weekday == 4:  # Friday
            return dt.time() < self.week_close_utc
        return True

    def sessions_at(self, moment: datetime) -> tuple[SessionName, ...]:
        if not self.is_market_open(moment):
            return ()
        return tuple(session.name for session in self.sessions if session.contains(moment))

    def last_market_open_before(self, moment: datetime, *, max_days: int = 10) -> datetime | None:
        """آخرین زمانی که بازار باز بوده (برای محاسبه کهنگی در تعطیلات)."""
        dt = ensure_utc(moment)
        probe = dt
        for _ in range(max_days * 24 * 4):
            if self.is_market_open(probe):
                return probe
            probe -= timedelta(minutes=15)
        return None

    def reference_time(self, now: datetime) -> datetime:
        """زمان مرجع برای سنجش تازگی: اگر بازار بسته است، آخرین لحظه باز بودن."""
        now = ensure_utc(now)
        if self.is_market_open(now):
            return now
        return self.last_market_open_before(now) or now

    # ---------------------------------------------------------------- کندل‌های مورد انتظار
    def expected_bar_times(self, start: datetime, end: datetime, timeframe: str | Timeframe) -> list[datetime]:
        tf = Timeframe.parse(timeframe)
        step = tf.delta
        if step >= timedelta(days=1):
            # کندل روزانه/هفتگی: فقط روزهای معاملاتی
            times: list[datetime] = []
            cursor = floor_to_timeframe(ensure_utc(start), tf.value)
            while cursor <= ensure_utc(end):
                if self.is_market_open(cursor):
                    times.append(cursor)
                cursor += step
            return times
        cursor = floor_to_timeframe(ensure_utc(start), tf.value)
        limit = ensure_utc(end)
        times = []
        while cursor <= limit:
            if self.is_market_open(cursor):
                times.append(cursor)
            cursor += step
        return times

    def last_closed_bar_time(self, now: datetime, timeframe: str | Timeframe) -> datetime | None:
        tf = Timeframe.parse(timeframe)
        candidate = floor_to_timeframe(ensure_utc(now), tf.value)
        if candidate + tf.delta > ensure_utc(now):
            candidate -= tf.delta
        for _ in range(24 * 7):
            if self.is_market_open(candidate):
                return candidate
            candidate -= tf.delta
        return None

    def is_stale(self, latest_available_at: datetime, now: datetime, timeframe: str | Timeframe, *, grace_seconds: int = 300,
                 max_age_bars: float = 1.5) -> bool:
        tf = Timeframe.parse(timeframe)
        reference = self.reference_time(now)
        age = (reference - ensure_utc(latest_available_at)).total_seconds()
        threshold = tf.minutes * 60 * max_age_bars + grace_seconds
        return age > threshold


def default_holidays() -> set[date]:
    """تعطیلات تقریبی بازار فارکس برای سال‌های ۲۰۲۵–۲۰۲۷."""
    return {
        date(2025, 1, 1), date(2025, 4, 18), date(2025, 12, 25), date(2025, 12, 26),
        date(2026, 1, 1), date(2026, 4, 3), date(2026, 12, 25), date(2026, 12, 26),
        date(2027, 1, 1), date(2027, 3, 26), date(2027, 12, 25), date(2027, 12, 26),
    }
