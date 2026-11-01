"""زمان: همه محاسبات داخلی UTC، تبدیل فقط در لایه نمایش."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Final

UTC: Final = timezone.utc

TIMEFRAME_MINUTES: Final[dict[str, int]] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
    "W1": 10080,
}

_ISO_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[T ](?P<time>\d{2}:\d{2}(?::\d{2})?)(?:\.(?P<frac>\d{1,6}))?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


def utcnow() -> datetime:
    """زمان جاری UTC (با ثانیه دقیق برای پایداری خروجی‌ها)."""
    return datetime.now(tz=UTC).replace(microsecond=0)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_ts(value: str | datetime) -> datetime:
    """تجزیه ISO-8601 با پشتیبانی Z؛ زمان بدون منطقه به‌عنوان UTC تلقی می‌شود."""
    if isinstance(value, datetime):
        return ensure_utc(value)
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        match = _ISO_RE.match(text)
        if not match:
            raise ValueError(f"timestamp نامعتبر: {value!r}") from None
        base = f"{match.group('date')}T{match.group('time')}"
        frac = match.group("frac")
        if frac:
            base += f".{frac.ljust(6, '0')}"
        tz = match.group("tz") or "Z"
        parsed = datetime.fromisoformat(base + ("+00:00" if tz == "Z" else tz))
    return ensure_utc(parsed)


def format_ts(value: datetime) -> str:
    """قالب قراردادی: YYYY-MM-DDTHH:MM:SSZ"""
    dt = ensure_utc(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def timeframe_delta(timeframe: str) -> timedelta:
    try:
        return timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    except KeyError:
        raise ValueError(f"timeframe پشتیبانی‌نشده: {timeframe!r}") from None


def floor_to_timeframe(value: datetime, timeframe: str) -> datetime:
    """گرد کردن زمان شروع کندل به شبکه زمانی (UTC)."""
    dt = ensure_utc(value)
    minutes = TIMEFRAME_MINUTES[timeframe]
    if minutes >= 1440:
        if minutes == 10080:
            monday = dt - timedelta(days=dt.weekday())
            return monday.replace(hour=0, minute=0, second=0, microsecond=0)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    total = dt.hour * 60 + dt.minute
    floored = total - (total % minutes)
    return dt.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)


def to_local(value: datetime, tz_name: str) -> datetime:
    from zoneinfo import ZoneInfo

    return ensure_utc(value).astimezone(ZoneInfo(tz_name))


def humanize_age(seconds: float) -> str:
    seconds = abs(float(seconds))
    if seconds < 60:
        return f"{seconds:.0f} ثانیه"
    if seconds < 3600:
        return f"{seconds / 60:.1f} دقیقه"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} ساعت"
    return f"{seconds / 86400:.1f} روز"
