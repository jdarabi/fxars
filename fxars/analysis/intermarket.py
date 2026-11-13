"""شواهد بین‌بازاری: همبستگی و حرکت سری مرجع با کنترل هم‌زمانی زمان."""

from __future__ import annotations

from fxars.analysis.context import AnalysisContext
from fxars.analysis.evidence import EvidenceFactory
from fxars.core.numerics import clamp, correlation, zscore
from fxars.core.timeutil import format_ts
from fxars.domain.enums import Direction, EvidenceFamily
from fxars.domain.models import Evidence

MODULE_VERSION = "1.0.0"


class IntermarketModule:
    module_id = "intermarket.correlation"
    version = MODULE_VERSION

    def compute(self, context: AnalysisContext, factory: EvidenceFactory) -> list[Evidence]:
        settings = context.settings
        references = context.references or {}
        if not references:
            return []
        evidences: list[Evidence] = []
        window = settings.intermarket_window

        for reference_id, reference_candles in references.items():
            if not reference_candles:
                continue
            by_time = {candle.open_time: candle for candle in reference_candles}
            main_returns: list[float] = []
            ref_returns: list[float] = []
            aligned: list[tuple[int, float, float]] = []

            for index in range(1, context.n):
                candle = context.candles[index]
                previous = context.candles[index - 1]
                reference = by_time.get(candle.open_time)
                reference_previous = by_time.get(previous.open_time)
                if reference is None or reference_previous is None:
                    continue
                if reference.available_at > candle.available_at:
                    continue
                # FIX-09-NO-ZERO-RETURN: اگر close صفر باشد، ردیف را رد کن (نه بازده جعلی صفر)
                if not previous.close or not reference_previous.close:
                    continue
                main_return = float((candle.close - previous.close) / previous.close)
                ref_return = float((reference.close - reference_previous.close) / reference_previous.close)
                main_returns.append(main_return)
                ref_returns.append(ref_return)
                aligned.append((index, main_return, ref_return))

            if len(aligned) < window + 5:
                continue

            for position, (index, _main_return, ref_return) in enumerate(aligned):
                if position < window:
                    continue
                main_slice = main_returns[position - window:position + 1]
                ref_slice = ref_returns[position - window:position + 1]
                corr = correlation(main_slice, ref_slice)
                if abs(corr) < settings.intermarket_min_correlation:
                    continue
                z = zscore(ref_return, ref_slice)
                if abs(z) < 0.8:
                    continue
                direction = Direction.LONG if ref_return * corr > 0 else Direction.SHORT
                strength = clamp(0.22 + 0.30 * min(1.0, abs(z) / 2.0) * min(1.0, abs(corr)), 0.2, 0.70)
                candle = context.candles[index]
                reference = by_time[candle.open_time]
                evidences.append(
                    factory.create(
                        module_id=f"{self.module_id}.{reference_id.lower()}",
                        module_version=self.version,
                        family=EvidenceFamily.INTERMARKET,
                        direction=direction,
                        strength=strength,
                        confidence=clamp(strength * 0.75, 0, 1),
                        observed_at=candle.open_time,
                        available_at=max(candle.available_at, reference.available_at),
                        explanation=(
                            f"همبستگی {reference_id} با نماد در پنجره {window} کندل: {corr:+.2f}؛ "
                            f"حرکت مرجع {ref_return * 100:+.3f}% (z={z:+.2f})."
                        ),
                        expiry=context.expiry(index, bars=3),
                        source_refs=(context.bar_ref(index), f"{reference_id}:{format_ts(reference.open_time)}"),
                        params={
                            "reference": reference_id,
                            "window": window,
                            "min_correlation": settings.intermarket_min_correlation,
                        },
                    )
                )
        return evidences


def latest_correlation(context: AnalysisContext, reference_id: str) -> float | None:
    """همبستگی جاری برای خلاصه اجرای تحلیل."""
    reference = context.reference(reference_id)
    if not reference:
        return None
    by_time = {candle.open_time: candle for candle in reference}
    main: list[float] = []
    ref: list[float] = []
    for index in range(1, context.n):
        candle = context.candles[index]
        previous = context.candles[index - 1]
        item = by_time.get(candle.open_time)
        item_previous = by_time.get(previous.open_time)
        if item is None or item_previous is None or item.available_at > candle.available_at:
            continue
        if not previous.close or not item_previous.close:
            continue
        main.append(float((candle.close - previous.close) / previous.close))
        ref.append(float((item.close - item_previous.close) / item_previous.close))
    window = context.settings.intermarket_window
    if len(main) < window:
        return None
    return correlation(main[-window:], ref[-window:])
