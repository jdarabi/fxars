"""اعتبارسنجی قرارداد کندل (بخش ۶-۲ و ۶-۵ سند)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from fxars.core.numerics import to_decimal
from fxars.core.timeutil import floor_to_timeframe, utcnow
from fxars.domain.enums import QualityStatus, Timeframe
from fxars.domain.models import Candle, Instrument
from fxars.instruments.calendar import TradingCalendar


@dataclass(frozen=True)
class CandleAssessment:
    status: QualityStatus
    flags: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return self.status is QualityStatus.VALID


class CandleValidator:
    """قواعد ساختاری هر کندل؛ قواعد توالی در DataQualityEngine اعمال می‌شود."""

    def __init__(self, instrument: Instrument, *, max_spread_pips: Decimal = Decimal("20"),
                 now: datetime | None = None, calendar: TradingCalendar | None = None) -> None:
        self.instrument = instrument
        self.max_spread_pips = to_decimal(max_spread_pips)
        self.now = now
        self.calendar = calendar

    def assess(self, candle: Candle) -> CandleAssessment:
        hard: list[str] = []
        soft: list[str] = []
        reasons: list[str] = []
        inst = self.instrument
        tf = Timeframe.parse(candle.timeframe)

        if candle.instrument_id != inst.instrument_id:
            hard.append("instrument_mismatch")
            reasons.append("شناسه نماد با مشخصات قراردادی سازگار نیست.")

        if self.calendar is not None:
            aligned = self.calendar.is_aligned_bar(candle.open_time, tf)
        else:
            aligned = candle.open_time == floor_to_timeframe(candle.open_time, tf.value)
        if not aligned:
            # شبکهٔ روزانه/۴ساعته تابع نیمه‌شب سرور است و در هفته‌های اختلاف DST
            # یک ساعت جابه‌جا می‌شود؛ برای این تایم‌فریم‌ها هشدار نرم است.
            (soft if tf.minutes >= 240 else hard).append("misaligned_bar")
            reasons.append("زمان شروع کندل با شبکه زمانی هم‌تراز نیست.")

        prices = (candle.open, candle.high, candle.low, candle.close)
        if any(price <= 0 for price in prices):
            hard.append("non_positive_price")
            reasons.append("قیمت صفر یا منفی است.")
        if candle.high < candle.low:
            hard.append("high_below_low")
            reasons.append("High کمتر از Low است.")
        if candle.high < max(candle.open, candle.close):
            hard.append("high_below_body")
            reasons.append("High کمتر از بدنه کندل است.")
        if candle.low > min(candle.open, candle.close):
            hard.append("low_above_body")
            reasons.append("Low بیشتر از بدنه کندل است.")

        quantum = inst.price_quantum
        for name, price in zip(("open", "high", "low", "close"), prices):
            if price.quantize(quantum) != price:
                soft.append(f"excess_precision_{name}")
                reasons.append(f"دقت {name} بیش از digits نماد است.")

        if candle.spread is not None:
            spread_pips = candle.spread / inst.pip_size
            if spread_pips > self.max_spread_pips:
                soft.append("spread_anomaly")
                reasons.append("اسپرد خارج از محدوده متعارف است.")
            if spread_pips < 0:
                hard.append("negative_spread")
                reasons.append("اسپرد منفی است.")

        if candle.tick_volume == 0:
            soft.append("zero_tick_volume")
            reasons.append("تیک‌والیوم صفر است؛ احتمال نقص فید.")
        if not candle.is_closed:
            soft.append("unclosed_bar")
            reasons.append("کندل بسته نشده است.")
        # FIX-P0-SUSPECT-HARD: اگر is_closed=true ولی available_at قبل از close_time است،
        # یعنی داده قبل از بسته‌شدن کندل در دسترس بوده → Look-ahead → INVALID
        if candle.is_closed and candle.available_at < candle.close_time:
            hard.append("available_at_before_close")
            reasons.append("کندل به‌عنوان بسته اعلام شده ولی available_at قبل از close_time است (Look-ahead).")
        if self.now is not None:
            if candle.available_at > self.now + timedelta(minutes=5):
                soft.append("future_available_at")
                reasons.append("زمان دسترس‌پذیری در آینده است.")
            if candle.ingested_at < candle.available_at - timedelta(days=1):
                soft.append("late_ingestion")
                reasons.append("تأخیر ورود داده بیش از حد است.")

        if hard:
            return CandleAssessment(QualityStatus.INVALID, tuple(hard + soft), tuple(reasons))
        if soft:
            return CandleAssessment(QualityStatus.SUSPECT, tuple(soft), tuple(reasons))
        return CandleAssessment(QualityStatus.VALID, (), ())


def assess_candles(candles: list[Candle], instrument: Instrument, *, now: datetime | None = None,
                   max_spread_pips: Decimal = Decimal("20")) -> list[CandleAssessment]:
    validator = CandleValidator(instrument, max_spread_pips=max_spread_pips, now=now or utcnow())
    return [validator.assess(candle) for candle in candles]
