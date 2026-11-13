"""تقویم معاملاتی: سشن‌ها، DST، تعطیلات و کندل‌های مورد انتظار.

هدف: کیفیت داده و Freshness نباید در تعطیلات/تعطیلی بازار هشدار کاذب بدهد.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fxars.core.timeutil import ensure_utc
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

# اختلاف حداکثری مرز DST اروپا و آمریکا؛ شبکهٔ روزانه/۴ساعته بروکر در آن هفته‌ها ۱ ساعت جابه‌جا می‌شود.
GRID_TOLERANCE = timedelta(hours=1)

# توقف روزانهٔ بروکر در مرز سشن (۱۷:۰۰ نیویورک): فارکس ~۱۵ دقیقه، فلزات ~۶۰ دقیقه.
DEFAULT_DAILY_BREAK_MINUTES = 15
DEFAULT_METAL_BREAK_MINUTES = 60
METAL_PREFIXES = ("XAU", "XAG")


def _is_metal(instrument_id: str | None) -> bool:
    return bool(instrument_id) and instrument_id.upper().startswith(METAL_PREFIXES)


class TradingCalendar:
    """تقویم فارکس ۲۴/۵؛ مرز هفته با ساعت نیویورک محاسبه می‌شود تا DST رعایت شود."""

    def __init__(
        self,
        holidays: set[date] | None = None,
        *,
        sessions: tuple[Session, ...] = DEFAULT_SESSIONS,
        week_open_local: time = time(17, 0),
        week_close_local: time = time(17, 0),
        market_timezone: str = "America/New_York",
        early_closes: Mapping[date, time] | None = None,
        metal_holidays: Iterable[date] | None = None,
        daily_break_minutes: int = DEFAULT_DAILY_BREAK_MINUTES,
        metal_break_minutes: int = DEFAULT_METAL_BREAK_MINUTES,
    ) -> None:
        self.holidays = set(holidays or ())
        self.sessions = sessions
        self.week_open_local = week_open_local
        self.week_close_local = week_close_local
        self.market_timezone = market_timezone
        self._market_tz = ZoneInfo(market_timezone)
        self.early_closes = dict(early_closes or {})
        self.metal_holidays = set(metal_holidays or ())
        self.daily_break_minutes = daily_break_minutes
        self.metal_break_minutes = metal_break_minutes

    # ---------------------------------------------------------------- روز معاملاتی
    def trading_date(self, moment: datetime) -> date:
        """روز معاملاتی از ۱۷:۰۰ نیویورک عوض می‌شود؛ سشنِ یکشنبه‌شب متعلق به دوشنبه است."""
        local = ensure_utc(moment).astimezone(self._market_tz)
        if local.time() >= self.week_open_local:
            return (local + timedelta(days=1)).date()
        return local.date()

    def trading_day_start(self, moment: datetime) -> datetime:
        """آغاز روز معاملاتی جاری به UTC (۱۷:۰۰ نیویورک روز قبل، DST-aware).

        شمارش «معاملات امروز» و سود/زیان روزانه باید با همین مرز انجام شود،
        نه نیمه‌شب UTC؛ وگرنه در تهران/نیویورک شمارش چند ساعت جابه‌جا می‌شود.
        """
        day = self.trading_date(moment)
        previous = day - timedelta(days=1)
        local = datetime.combine(previous, self.week_open_local, tzinfo=self._market_tz)
        return local.astimezone(UTC)

    def is_holiday(self, trading_day: date, *, instrument_id: str | None = None) -> bool:
        if trading_day in self.holidays:
            return True
        return _is_metal(instrument_id) and trading_day in self.metal_holidays

    def is_session_traded(self, trading_day: date, *, instrument_id: str | None = None) -> bool:
        """آیا برای این روز معاملاتی سشنی برگزار می‌شود؟ (تعطیلی زودتر از موعد هم سشن دارد.)"""
        return trading_day.weekday() < 5 and not self.is_holiday(trading_day, instrument_id=instrument_id)

    def daily_break(self, instrument_id: str | None = None) -> timedelta:
        minutes = self.metal_break_minutes if _is_metal(instrument_id) else self.daily_break_minutes
        return timedelta(minutes=minutes)

    # ---------------------------------------------------------------- وضعیت بازار
    def is_market_open(self, moment: datetime, *, instrument_id: str | None = None) -> bool:
        # بازار فارکس با ساعت ۱۷:۰۰ نیویورک یکشنبه باز و جمعه بسته می‌شود؛
        # محاسبه در وقت محلی، جابه‌جایی DST را خودکار پوشش می‌دهد.
        local = ensure_utc(moment).astimezone(self._market_tz)
        weekday = local.weekday()  # Monday=0 ... Sunday=6
        if weekday == 5:
            return False
        if weekday == 6 and local.time() < self.week_open_local:
            return False
        if weekday == 4 and local.time() >= self.week_close_local:
            return False
        trading_day = self.trading_date(moment)
        if self.is_holiday(trading_day, instrument_id=instrument_id):
            return False
        close_at = self.early_closes.get(trading_day)
        if close_at is not None and local.date() == trading_day and local.time() >= close_at:
            return False
        # توقف نگهداری بروکر بلافاصله پس از بسته‌شدن سشن روزانه
        break_start = self.week_open_local
        start_seconds = break_start.hour * 3600 + break_start.minute * 60 + break_start.second
        current_seconds = local.hour * 3600 + local.minute * 60 + local.second
        break_seconds = int(self.daily_break(instrument_id).total_seconds())
        if start_seconds <= current_seconds < start_seconds + break_seconds:
            return False
        return True

    def sessions_at(self, moment: datetime, *, instrument_id: str | None = None) -> tuple[SessionName, ...]:
        if not self.is_market_open(moment, instrument_id=instrument_id):
            return ()
        return tuple(session.name for session in self.sessions if session.contains(moment))

    def last_market_open_before(self, moment: datetime, *, instrument_id: str | None = None,
                                max_days: int = 10) -> datetime | None:
        """آخرین زمانی که بازار باز بوده (برای محاسبه کهنگی در تعطیلات)."""
        dt = ensure_utc(moment)
        probe = dt
        for _ in range(max_days * 24 * 60):
            if self.is_market_open(probe, instrument_id=instrument_id):
                return probe
            probe -= timedelta(minutes=1)
        return None

    def reference_time(self, now: datetime, *, instrument_id: str | None = None) -> datetime:
        """زمان مرجع برای سنجش تازگی: اگر بازار بسته است، آخرین لحظه باز بودن."""
        now = ensure_utc(now)
        if self.is_market_open(now, instrument_id=instrument_id):
            return now
        return self.last_market_open_before(now, instrument_id=instrument_id) or now

    # ---------------------------------------------------------------- کندل‌های مورد انتظار
    def week_open(self, moment: datetime) -> datetime:
        """بازگشایی هفتهٔ جاری به UTC؛ لنگر شبکهٔ کندل‌هاست."""
        local = ensure_utc(moment).astimezone(self._market_tz)
        days_since_sunday = (local.weekday() + 1) % 7
        sunday = (local - timedelta(days=days_since_sunday)).date()
        anchor_local = datetime.combine(sunday, self.week_open_local, tzinfo=self._market_tz)
        return anchor_local.astimezone(UTC)

    def bar_floor(self, moment: datetime, timeframe: str | Timeframe) -> datetime:
        """شبکهٔ کندل از بازگشایی هفته شروع می‌شود، نه نیمه‌شب UTC.

        کندل‌های روزانه/۴ساعته بروکر به نیمه‌شب وقت سرور لنگر دارند که با
        بازگشایی سشن (۱۷:۰۰ نیویورک) هم‌تراز است؛ لنگر UTC باعث هشدار کاذب
        «misaligned_bar» برای این تایم‌فریم‌ها می‌شد.
        """
        tf = Timeframe.parse(timeframe)
        step = tf.delta
        exact = ensure_utc(moment)
        anchor = self.week_open(exact)
        return anchor + ((exact - anchor) // step) * step

    def is_aligned_bar(self, moment: datetime, timeframe: str | Timeframe) -> bool:
        """هم‌ترازی با شبکهٔ سشن؛ برای H4/D1/W1 یک ساعت اختلاف DST اروپا/آمریکا مجاز است."""
        tf = Timeframe.parse(timeframe)
        offset = ensure_utc(moment) - self.bar_floor(moment, tf)
        tolerance = GRID_TOLERANCE if tf.minutes >= 240 else timedelta(0)
        return timedelta(0) <= offset <= tolerance

    def is_bar_expected(self, open_time: datetime, timeframe: str | Timeframe, *,
                        instrument_id: str | None = None) -> bool:
        """کندل وقتی انتظار می‌رود که بخشی از بازه‌اش در بازار باز باشد.

        توقف ۱۵ دقیقه‌ای فارکس کندل M15 ساعت ۱۷:۰۰ را حذف می‌کند، اما کندل‌های
        M30/H1 که از توقف عبور می‌کنند و در بازار باز بسته می‌شوند باقی می‌مانند.
        کندل روزانهٔ روزِ تعطیلی زودتر ممکن است هم آغاز و هم پایانش بسته باشد
        ولی وسط روز معامله شده باشد؛ پس لحظهٔ بازگشایی پس از توقف هم بررسی می‌شود.
        """
        tf = Timeframe.parse(timeframe)
        start = ensure_utc(open_time)
        # کندل روزانه/هفتگی متعلق به سشنِ یک روز معاملاتی است؛ مرز ۲۴ساعتهٔ UTC
        # در هفتهٔ DST می‌تواند تا سشن یکشنبه‌شب امتداد یابد و نباید کندل شنبه بسازد.
        if tf.minutes >= 1440:
            return self.is_session_traded(self.trading_date(start), instrument_id=instrument_id)
        end = start + tf.delta
        if self.is_market_open(start, instrument_id=instrument_id):
            return True
        if self.is_market_open(end - timedelta(seconds=1), instrument_id=instrument_id):
            return True
        resume = start + self.daily_break(instrument_id)
        return resume < end and self.is_market_open(resume, instrument_id=instrument_id)

    def expected_bar_times(self, start: datetime, end: datetime, timeframe: str | Timeframe, *,
                           instrument_id: str | None = None) -> list[datetime]:
        tf = Timeframe.parse(timeframe)
        step = tf.delta
        cursor = ensure_utc(start)
        limit = ensure_utc(end)
        times: list[datetime] = []
        while cursor <= limit:
            if self.is_bar_expected(cursor, tf, instrument_id=instrument_id):
                times.append(cursor)
            cursor += step
        return times

    def last_closed_bar_time(self, now: datetime, timeframe: str | Timeframe, *,
                             instrument_id: str | None = None) -> datetime | None:
        tf = Timeframe.parse(timeframe)
        candidate = self.bar_floor(now, tf)
        if candidate + tf.delta > ensure_utc(now):
            candidate -= tf.delta
        for _ in range(24 * 7):
            if self.is_bar_expected(candidate, tf, instrument_id=instrument_id):
                return candidate
            candidate -= tf.delta
        return None

    def is_stale(self, latest_available_at: datetime, now: datetime, timeframe: str | Timeframe, *,
                 instrument_id: str | None = None, grace_seconds: int = 300,
                 max_age_bars: float = 1.5) -> bool:
        tf = Timeframe.parse(timeframe)
        reference = self.reference_time(now, instrument_id=instrument_id)
        age = (reference - ensure_utc(latest_available_at)).total_seconds()
        threshold = tf.minutes * 60 * max_age_bars + grace_seconds
        return age > threshold


def default_holidays() -> set[date]:
    """تعطیلات عمومی بازار به‌صورت تاریخ معاملاتی: کریسمس و سال نو (۲۰۲۴–۲۰۲۷).

    کریسمس با نیمه‌شب ۲۴ دسامبر شروع می‌شود و سال نو با نیمه‌شب ۳۱ دسامبر؛
    بازگشایی همان عصر (۱۷:۰۰ نیویورک) متعلق به روز معاملاتی بعد است.
    """
    return {
        date(2024, 12, 25), date(2025, 1, 1),
        date(2025, 12, 25), date(2026, 1, 1),
        date(2026, 12, 25), date(2027, 1, 1),
        date(2027, 12, 25), date(2028, 1, 1),
    }


def default_metal_holidays() -> set[date]:
    """تعطیلات اضافی فلزات: جمعهٔ مقدس؛ فارکس در این روز معامله می‌کند اما XAU/XAG نه."""
    return {date(2025, 4, 18), date(2026, 4, 3), date(2027, 3, 26)}


def default_early_closes() -> dict[date, time]:
    """تعطیلی زودتر از موعد در آستانهٔ تعطیلات؛ ساعت به وقت نیویورک."""
    return {
        date(2024, 12, 24): time(13, 0),
        date(2024, 12, 31): time(13, 0),
        date(2025, 7, 4): time(13, 0),
        date(2025, 12, 24): time(13, 0),
        date(2025, 12, 31): time(13, 0),
        date(2026, 7, 3): time(13, 0),
        date(2026, 12, 24): time(13, 0),
        date(2026, 12, 31): time(13, 0),
        date(2027, 12, 24): time(13, 0),
    }
