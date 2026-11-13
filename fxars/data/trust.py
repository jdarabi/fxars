"""Data Trust Score (DTS) — بخش ۴-۲ سند تکمیلی ۱.۱.

DTS یک امتیاز ۰..۱ از پنج مؤلفه است:
    Freshness, Completeness, Consistency, SchemaValidity, SourceReliability

قاعده Fail-Safe: اگر DTS < min_score باشد، تحلیل مجاز نیست و خروجی
``NO_TRADE`` با دلیل ``DATA_UNTRUSTED`` صادر می‌شود. این ماژول هیچ داده‌ای
را تغییر نمی‌دهد و فقط کیفیت را می‌سنجد.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable

from fxars.config.decision import TrustPolicy
from fxars.core.numerics import clamp
from fxars.core.timeutil import ensure_utc
from fxars.domain.enums import QualityStatus, Timeframe
from fxars.domain.models import Candle


@dataclass(frozen=True)
class TrustBreakdown:
    """اجزای DTS با دلیل هر مؤلفه؛ برای نمایش در Uncertainty Panel."""

    freshness: float
    completeness: float
    consistency: float
    schema_validity: float
    source_reliability: float
    score: float
    status: str
    reasons: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_trusted(self) -> bool:
        return self.status in {"TRUSTED", "DEGRADED"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "freshness": round(self.freshness, 4),
            "completeness": round(self.completeness, 4),
            "consistency": round(self.consistency, 4),
            "schema_validity": round(self.schema_validity, 4),
            "source_reliability": round(self.source_reliability, 4),
            "score": round(self.score, 4),
            "status": self.status,
            "reasons": list(self.reasons),
            "details": self.details,
        }


def _empty_breakdown(reason: str, policy: TrustPolicy) -> TrustBreakdown:
    return TrustBreakdown(
        freshness=0.0,
        completeness=0.0,
        consistency=0.0,
        schema_validity=0.0,
        source_reliability=0.0,
        score=0.0,
        status="UNTRUSTED",
        reasons=(reason,),
        details={"min_score": policy.min_score},
    )


def compute_data_trust(
    candles: Iterable[Candle],
    *,
    as_of: datetime | None = None,
    timeframe: str | None = None,
    expected_bar_times: Iterable[datetime] | None = None,
    policy: TrustPolicy | None = None,
    source_reliability: dict[str, float] | None = None,
) -> TrustBreakdown:
    """محاسبه DTS برای مجموعه کندل‌های یک نماد/منبع.

    ``expected_bar_times`` اختیاری است؛ در نبود آن، انتظار از فاصله زمانی
    اولین/آخرین کندل و ``timeframe`` ساخته می‌شود. تحلیل‌گر تقویم معاملاتی را
    عبور می‌دهد تا تعطیلات به‌اشتباه «کمبود داده» شمرده نشوند.
    """
    policy = policy or TrustPolicy()
    ordered = sorted(candles, key=lambda item: item.open_time)
    if not ordered:
        return _empty_breakdown("هیچ کندلی برای ارزیابی اعتماد داده موجود نیست.", policy)

    tf = Timeframe.parse(timeframe or ordered[-1].timeframe)
    reference = ensure_utc(as_of) if as_of else ordered[-1].available_at
    latest = max(ordered, key=lambda item: item.available_at)

    # 1) Freshness: فاصله آخرین داده از cutoff بر حسب تعداد کندل.
    age_seconds = max(0.0, (reference - latest.available_at).total_seconds())
    age_bars = age_seconds / max(tf.delta.total_seconds(), 1.0)
    freshness = clamp(1.0 - age_bars / max(policy.freshness_max_age_bars, 1e-9), 0.0, 1.0)
    if freshness == 0.0:
        freshness_reason = (
            f"آخرین داده {age_bars:.1f} کندل از زمان تصمیم عقب‌تر است "
            f"(حد مجاز {policy.freshness_max_age_bars:.1f} کندل)."
        )

    # 2) Completeness: نسبت کندل‌های موجود به کندل‌های مورد انتظار.
    if expected_bar_times is not None:
        expected = {ensure_utc(item) for item in expected_bar_times}
        present = {ensure_utc(item.open_time) for item in ordered}
        expected_count = len(expected) or 1
        completeness = clamp(len(expected & present) / expected_count, 0.0, 1.0)
        missing = sorted(expected - present)
    else:
        span = latest.open_time - ordered[0].open_time
        expected_count = int(span.total_seconds() // tf.delta.total_seconds()) + 1
        completeness = clamp(len({item.open_time for item in ordered}) / max(expected_count, 1), 0.0, 1.0)
        missing = []

    # 3) Consistency: OHLC، تکرار، شکاف و دامنه اسپرد.
    invalid_ohlc = sum(
        1
        for candle in ordered
        if candle.high < max(candle.open, candle.close)
        or candle.low > min(candle.open, candle.close)
        or candle.high < candle.low
    )
    duplicate_times = sum(
        count - 1 for count in Counter(item.open_time for item in ordered).values() if count > 1
    )
    gaps = 0
    for previous, current in zip(ordered, ordered[1:]):
        step_bars = (current.open_time - previous.open_time) / tf.delta
        if step_bars > policy.max_gap_bars + 1:
            gaps += 1
    spread_anomalies = 0
    spreads = [float(item.spread) for item in ordered if item.spread is not None and item.spread > 0]
    if spreads:
        median = sorted(spreads)[len(spreads) // 2]
        if median > 0:
            spread_anomalies = sum(
                1 for value in spreads if value > median * policy.max_spread_jump_ratio
            )
    issue_count = invalid_ohlc + duplicate_times + gaps + spread_anomalies
    consistency = clamp(1.0 - issue_count / max(len(ordered), 1) * 5.0, 0.0, 1.0)

    # 4) SchemaValidity: فیلدهای اجباری، ترتیب زمانی و وضعیت کیفیت.
    invalid_rows = 0
    for candle in ordered:
        if candle.timeframe != tf.value or not candle.instrument_id or not candle.source_id:
            invalid_rows += 1
        elif candle.available_at < candle.open_time or candle.open_time.tzinfo is None:
            invalid_rows += 1
        elif candle.quality_status is QualityStatus.INVALID or not candle.is_closed:
            invalid_rows += 1
        elif not all(isinstance(getattr(candle, name), Decimal) for name in ("open", "high", "low", "close")):
            invalid_rows += 1
    schema_validity = clamp(1.0 - invalid_rows / len(ordered), 0.0, 1.0)

    # 5) SourceReliability: نرخ خطای منبع/نسخه؛ پیش‌فرض محافظه‌کارانه قابل تنظیم.
    sources = sorted({item.source_id for item in ordered})
    reliability_values = [
        float((source_reliability or {}).get(source, policy.default_source_reliability))
        for source in sources
    ]
    source_reliability_score = clamp(
        sum(reliability_values) / len(reliability_values) if reliability_values else 0.0,
        0.0,
        1.0,
    )

    score = clamp(
        policy.w_freshness * freshness
        + policy.w_completeness * completeness
        + policy.w_consistency * consistency
        + policy.w_schema_validity * schema_validity
        + policy.w_source_reliability * source_reliability_score,
        0.0,
        1.0,
    )
    reasons: list[str] = []
    if freshness < 0.5:
        reasons.append(
            freshness_reason
            if "freshness_reason" in locals()
            else "داده از زمان تصمیم عقب‌تر از حد مجاز است."
        )
    if completeness < 0.9:
        reasons.append(
            f"کمبود داده: {completeness:.0%} کندل‌های مورد انتظار موجود است"
            + (f" ({len(missing)} کندل غایب)." if missing else ".")
        )
    if consistency < 0.9:
        reasons.append(
            f"ناسازگاری داده: OHLC نامعتبر={invalid_ohlc}، تکرار={duplicate_times}، "
            f"شکاف={gaps}، اسپرد غیرعادی={spread_anomalies}."
        )
    if schema_validity < 1.0:
        reasons.append(f"{invalid_rows} رکورد با قرارداد داده سازگار نیست.")
    if source_reliability_score < 0.8:
        reasons.append("قابلیت اعتماد منبع داده کمتر از حد مطلوب است.")

    if score >= policy.min_score:
        status = "TRUSTED" if score >= min(0.95, policy.min_score + 0.15) else "DEGRADED"
    else:
        status = "UNTRUSTED"

    return TrustBreakdown(
        freshness=freshness,
        completeness=completeness,
        consistency=consistency,
        schema_validity=schema_validity,
        source_reliability=source_reliability_score,
        score=score,
        status=status,
        reasons=tuple(reasons),
        details={
            "min_score": policy.min_score,
            "bars": len(ordered),
            "expected_bars": expected_count,
            "sources": sources,
            "age_bars": round(age_bars, 3),
            "decision_time": reference.isoformat(),
        },
    )
