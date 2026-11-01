"""شواهد بنیادی: غافلگیری داده‌های اقتصادی با احترام به Bitemporal (available_at)."""

from __future__ import annotations

from datetime import timedelta

from fxars.analysis.context import AnalysisContext
from fxars.analysis.evidence import EvidenceFactory
from fxars.core.numerics import clamp
from fxars.core.timeutil import format_ts
from fxars.domain.enums import Direction, EventImportance, EvidenceFamily
from fxars.domain.models import Evidence

MODULE_VERSION = "1.0.0"

_IMPORTANCE_WEIGHT = {EventImportance.HIGH: 1.0, EventImportance.MEDIUM: 0.65, EventImportance.LOW: 0.35}


class FundamentalModule:
    module_id = "fundamental.event_surprise"
    version = MODULE_VERSION

    def compute(self, context: AnalysisContext, factory: EvidenceFactory) -> list[Evidence]:
        settings = context.settings
        instrument = context.instrument
        lookback = context.as_of - timedelta(hours=settings.fundamental_lookback_hours)
        evidences: list[Evidence] = []
        base = instrument.base_currency.upper()
        quote = instrument.quote_currency.upper()

        for event in context.economic_events:
            if event.actual is None or event.forecast is None:
                continue
            if event.available_at > context.as_of or event.event_time < lookback:
                continue
            ratio = event.surprise_ratio
            if ratio is None or abs(ratio) < settings.fundamental_surprise_floor:
                continue
            currency = event.currency.upper()
            if currency == base:
                sign = 1
            elif currency == quote:
                sign = -1
            else:
                continue
            direction = Direction.LONG if ratio * sign > 0 else Direction.SHORT
            weight = _IMPORTANCE_WEIGHT.get(event.importance, 0.5)
            strength = clamp(0.22 + 0.38 * min(1.0, abs(ratio) / 0.25) * weight, 0.15, 0.85)
            evidences.append(
                factory.create(
                    module_id=self.module_id,
                    module_version=self.version,
                    family=EvidenceFamily.FUNDAMENTAL,
                    direction=direction,
                    strength=strength,
                    confidence=clamp(strength * 0.8, 0, 1),
                    observed_at=event.available_at,
                    available_at=event.available_at,
                    explanation=(
                        f"{event.indicator} ({currency}): actual={format(event.actual, 'f')} در برابر "
                        f"forecast={format(event.forecast, 'f')}؛ غافلگیری {ratio * 100:+.1f}%."
                    ),
                    invalidation={"condition": "revision", "level": "event_revised"},
                    expiry=event.available_at + context.tf.delta * settings.evidence_horizon_bars,
                    source_refs=(f"event:{event.event_id}", f"event_time:{format_ts(event.event_time)}"),
                    params={"importance": event.importance.value, "surprise_floor": settings.fundamental_surprise_floor},
                )
            )
        return evidences
