"""موتور کیفیت داده: توالی، شکاف، تازگی، واگرایی منابع و صدور گزارش."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from fxars.config.settings import DataQualitySettings
from fxars.core.ids import stable_id
from fxars.core.numerics import to_decimal
from fxars.core.timeutil import format_ts, utcnow
from fxars.data.reconciliation import match_candles
from fxars.data.snapshot import candles_digest
from fxars.data.validation import CandleValidator
from fxars.domain.enums import QualityStatus, Timeframe
from fxars.domain.models import Candle, DataQualityIssue, DataQualityRun, Instrument
from fxars.instruments.calendar import TradingCalendar


class DataQualityEngine:
    def __init__(self, settings: DataQualitySettings, calendar: TradingCalendar | None = None) -> None:
        self.settings = settings
        self.calendar = calendar or TradingCalendar()

    def evaluate(
        self,
        *,
        instrument: Instrument,
        timeframe: str,
        source_id: str,
        candles: list[Candle],
        now: datetime | None = None,
        reference_candles: list[Candle] | None = None,
    ) -> DataQualityRun:
        checked_at = now or utcnow()
        tf = Timeframe.parse(timeframe)
        issues: list[DataQualityIssue] = []
        ordered = sorted(candles, key=lambda candle: candle.open_time)

        if not ordered:
            issues.append(DataQualityIssue("no_data", "ERROR", "هیچ کندلی برای این نماد/تایم‌فریم ثبت نشده است."))
            return DataQualityRun(
                run_id=stable_id("dq", instrument.instrument_id, tf.value, source_id, "empty", checked_at),
                instrument_id=instrument.instrument_id, timeframe=tf.value, source_id=source_id,
                checked_at=checked_at, total=0, valid=0, suspect=0, invalid=0, missing=0,
                stale=True, verdict="FAIL", issues=tuple(issues), latest_bar_age_seconds=0.0,
                latest_expected_at=self.calendar.last_closed_bar_time(
                    checked_at, tf, instrument_id=instrument.instrument_id,
                ),
            )

        duplicates = [time for time, count in Counter(candle.open_time for candle in ordered).items() if count > 1]
        for time in duplicates[: self.settings.max_reported_gaps]:
            issues.append(DataQualityIssue("duplicate_timestamp", "ERROR", "کندل تکراری با همان زمان شروع.", key=format_ts(time)))

        validator = CandleValidator(
            instrument, max_spread_pips=self.settings.max_spread_pips, now=checked_at,
            calendar=self.calendar,
        )
        statuses: list[QualityStatus] = []
        for index, candle in enumerate(ordered):
            assessment = validator.assess(candle)
            status = assessment.status
            flags = list(assessment.flags)
            reasons = list(assessment.reasons)

            # پرش قیمتی نسب به کندل قبلی (قاعده نرم)
            if index > 0:
                previous = ordered[index - 1]
                jump_pips = abs(candle.close - previous.close) / instrument.pip_size
                if jump_pips > self.settings.max_price_jump_pips:
                    if status.rank < QualityStatus.SUSPECT.rank:
                        status = QualityStatus.SUSPECT
                    flags.append("price_jump")
                    reasons.append(f"پرش قیمتی {jump_pips:.1f} پیپ نسبت به کندل قبل.")
            if flags and status is QualityStatus.VALID:
                status = QualityStatus.SUSPECT
            if status is not QualityStatus.VALID:
                issues.append(
                    DataQualityIssue(
                        "candle_quality", "ERROR" if status is QualityStatus.INVALID else "WARN",
                        "؛ ".join(reasons) or "کیفیت کندل پایین است.",
                        key=format_ts(candle.open_time),
                        details={"flags": flags, "status": status.value},
                    )
                )
            statuses.append(status)

        # شکاف داده بر اساس تقویم سشن (گزارش تطبیق صریح)
        match = match_candles(
            ordered, instrument_id=instrument.instrument_id, timeframe=tf.value,
            source_id=source_id, calendar=self.calendar, now=checked_at,
        )
        missing = match.missing
        missing_times = match.missing_times
        if missing > self.settings.gap_tolerance_bars:
            groups = _group_consecutive(missing_times, tf.delta)
            for group in groups[: self.settings.max_reported_gaps]:
                issues.append(
                    DataQualityIssue(
                        "missing_candles", "WARN",
                        f"{len(group)} کندل مورد انتظار در بازه {format_ts(group[0])} تا {format_ts(group[-1])} موجود نیست.",
                        key=format_ts(group[0]),
                        details={"count": len(group)},
                    )
                )

        latest = max(ordered, key=lambda candle: candle.available_at)
        stale = self.calendar.is_stale(
            latest.available_at, checked_at, tf,
            instrument_id=instrument.instrument_id,
            grace_seconds=self.settings.freshness_grace_seconds,
            max_age_bars=self.settings.max_bar_age_bars,
        )
        reference = self.calendar.reference_time(checked_at, instrument_id=instrument.instrument_id)
        age_seconds = max(0.0, (reference - latest.available_at).total_seconds())
        if stale:
            issues.append(
                DataQualityIssue(
                    "stale_data", "ERROR",
                    f"داده کهنه است: آخرین کندل {age_seconds / 60:.1f} دقیقه قبل در دسترس بوده است.",
                    key=format_ts(latest.available_at),
                    details={"age_seconds": round(age_seconds, 3), "threshold_bars": self.settings.max_bar_age_bars},
                )
            )

        if reference_candles:
            issues.extend(self._divergence(ordered, reference_candles, instrument))

        valid = sum(1 for status in statuses if status is QualityStatus.VALID)
        suspect = sum(1 for status in statuses if status is QualityStatus.SUSPECT)
        invalid = sum(1 for status in statuses if status is QualityStatus.INVALID)

        # FIX-02-VERDICT-SEVERITY: verdict بر اساس شدت Issueها
        severities = {issue.severity for issue in issues}
        if invalid > 0 or stale or "ERROR" in severities:
            verdict = "FAIL"
        elif suspect > 0 or missing > 0 or "WARN" in severities:
            verdict = "WARN"
        else:
            verdict = "PASS"

        digest = candles_digest(ordered)
        return DataQualityRun(
            run_id=stable_id("dq", instrument.instrument_id, tf.value, source_id, digest, checked_at),
            instrument_id=instrument.instrument_id,
            timeframe=tf.value,
            source_id=source_id,
            checked_at=checked_at,
            total=len(ordered),
            valid=valid,
            suspect=suspect,
            invalid=invalid,
            missing=missing,
            stale=stale,
            verdict=verdict,
            issues=tuple(issues),
            latest_bar_age_seconds=age_seconds,
            expected=match.expected,
            matched=match.matched,
            extra=match.extra,
            latest_expected_at=match.latest_expected_at,
            latest_present_at=match.latest_present_at,
        )

    def _divergence(self, primary: list[Candle], reference: list[Candle], instrument: Instrument) -> list[DataQualityIssue]:
        by_time = {candle.open_time: candle for candle in reference}
        issues: list[DataQualityIssue] = []
        threshold = self.settings.source_divergence_pips * instrument.pip_size
        for candle in primary:
            other = by_time.get(candle.open_time)
            if other is None:
                continue
            difference = abs(candle.close - other.close)
            if difference > threshold:
                issues.append(
                    DataQualityIssue(
                        "source_divergence", "WARN",
                        "اختلاف دو منبع بیش از آستانه مصوب است.",
                        key=format_ts(candle.open_time),
                        details={
                            "difference_pips": float(difference / instrument.pip_size),
                            "threshold_pips": float(self.settings.source_divergence_pips),
                            "sources": [candle.source_id, other.source_id],
                        },
                    )
                )
                if len(issues) >= self.settings.max_reported_gaps:
                    break
        return issues


def _group_consecutive(times: Iterable[datetime], step) -> list[list[datetime]]:
    ordered = sorted(times)
    groups: list[list[datetime]] = []
    for moment in ordered:
        if groups and moment - groups[-1][-1] == step:
            groups[-1].append(moment)
        else:
            groups.append([moment])
    return groups


def parse_decimal(value: str) -> Decimal:
    return to_decimal(value)
