"""موتور تحلیل: اجرای قطعی ماژول‌ها روی یک پنجره داده و تولید Evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from fxars.analysis import indicators as ind
from fxars.analysis.context import AnalysisContext, IndicatorSet
from fxars.analysis.evidence import EvidenceFactory
from fxars.analysis.fundamental import FundamentalModule
from fxars.analysis.intermarket import IntermarketModule, latest_correlation
from fxars.analysis.levels import LevelsModule
from fxars.analysis.regime import MomentumModule, TrendModule, VolatilityModule, VolumeModule
from fxars.analysis.structure import StructureModule, StructureResult
from fxars.config.settings import AnalysisSettings
from fxars.core.hashing import sha256_obj
from fxars.core.numerics import clamp
from fxars.core.timeutil import format_ts
from fxars.domain.models import Candle, EconomicEvent, Evidence, Instrument
from fxars.instruments.calendar import TradingCalendar


@dataclass
class AnalysisOutcome:
    instrument: Instrument
    timeframe: str
    as_of: datetime
    candles: list[Candle]
    indicators: IndicatorSet
    structure: StructureResult
    evidences: list[Evidence]
    summary: dict
    snapshot_id: str
    config_hash: str
    status: str = "COMPLETED"
    reason: str | None = None
    data_quality: dict = field(default_factory=dict)


class AnalysisEngine:
    def __init__(self, settings: AnalysisSettings, calendar: TradingCalendar | None = None) -> None:
        self.settings = settings
        self.calendar = calendar or TradingCalendar()
        self.modules = [
            StructureModule(),
            LevelsModule(),
            TrendModule(),
            MomentumModule(),
            VolatilityModule(),
            VolumeModule(),
            FundamentalModule(),
            IntermarketModule(),
        ]

    def analyze(
        self,
        *,
        instrument: Instrument,
        timeframe: str,
        candles: Sequence[Candle],
        as_of: datetime,
        run_id: str,
        economic_events: Sequence[EconomicEvent] = (),
        references: dict[str, list[Candle]] | None = None,
        config_hash: str = "",
    ) -> AnalysisOutcome:
        ordered = sorted(candles, key=lambda candle: candle.open_time)
        snapshot = _snapshot(ordered, instrument.instrument_id, timeframe)
        if len(ordered) < self.settings.min_bars:
            return AnalysisOutcome(
                instrument=instrument,
                timeframe=timeframe,
                as_of=as_of,
                candles=list(ordered),
                indicators=IndicatorSet.build([], self.settings),
                structure=StructureResult(),
                evidences=[],
                summary={"reason": "INSUFFICIENT_BARS", "bars": len(ordered), "required": self.settings.min_bars},
                snapshot_id=snapshot,
                config_hash=config_hash,
                status="INSUFFICIENT_DATA",
                reason=f"حداقل {self.settings.min_bars} کندل لازم است؛ {len(ordered)} کندل موجود است.",
            )

        indicators = IndicatorSet.build(ordered, self.settings)
        context = AnalysisContext(
            instrument=instrument,
            timeframe=timeframe,
            candles=list(ordered),
            as_of=as_of,
            settings=self.settings,
            indicators=indicators,
            calendar=self.calendar,
            economic_events=tuple(economic_events),
            references=references or {},
        )
        factory = EvidenceFactory(context, run_id)
        structure = StructureResult()
        for module in self.modules:
            result = module.compute(context, factory)
            if isinstance(result, StructureResult):
                structure = result

        evidences = list(factory.created)
        usable = [item for item in evidences if item.available_at <= as_of]
        usable.sort(key=lambda item: (item.available_at, item.module_id, item.observed_at, item.evidence_id))
        summary = self._summary(context, structure, usable, references or {})
        return AnalysisOutcome(
            instrument=instrument,
            timeframe=timeframe,
            as_of=as_of,
            candles=list(ordered),
            indicators=indicators,
            structure=structure,
            evidences=usable,
            summary=summary,
            snapshot_id=snapshot,
            config_hash=config_hash,
        )

    def _summary(
        self,
        context: AnalysisContext,
        structure: StructureResult,
        evidences: list[Evidence],
        references: dict[str, list[Candle]],
    ) -> dict:
        last = context.candles[-1]
        atr = context.indicators.atr[-1]
        atr_pips = round(float(atr / float(context.instrument.pip_size)), 2) if atr else None
        percentile = context.indicators.atr_percentile[-1]
        families: dict[str, int] = {}
        for evidence in evidences:
            families[evidence.family.value] = families.get(evidence.family.value, 0) + 1
        correlations = {}
        for reference_id in references:
            value = latest_correlation(context, reference_id)
            if value is not None:
                correlations[reference_id] = round(value, 4)
        return {
            "last_close": format(last.close, "f"),
            "last_bar_open": format_ts(last.open_time),
            "bars": context.n,
            "trend": structure.trend,
            "last_break": structure.last_break.kind if structure.last_break else None,
            "last_bos": structure.last_bos.kind if structure.last_bos else None,
            "last_choch": structure.last_choch.kind if structure.last_choch else None,
            "last_swing_high": format(structure.last_swing_high.price, "f") if structure.last_swing_high else None,
            "last_swing_low": format(structure.last_swing_low.price, "f") if structure.last_swing_low else None,
            "rsi": round(context.indicators.rsi[-1], 2) if context.indicators.rsi[-1] is not None else None,
            "roc": round(context.indicators.roc[-1] * 100, 4) if context.indicators.roc[-1] is not None else None,
            "atr_pips": atr_pips,
            "atr_percentile": round(percentile, 1) if percentile is not None else None,
            "session": list(context.calendar.sessions_at(context.as_of)),
            "market_open": context.calendar.is_market_open(context.as_of),
            "evidence_count": len(evidences),
            "families": families,
            "reference_correlations": correlations,
            "data_quality": {
                "latest_available_at": format_ts(last.available_at),
                "last_quality": last.quality_status.value,
                "sources": sorted({candle.source_id for candle in context.candles}),
            },
            "config_fingerprint": sha256_obj(context.settings.to_dict())[:16],
        }


def _snapshot(candles: Sequence[Candle], instrument_id: str, timeframe: str) -> str:
    from fxars.data.snapshot import snapshot_id

    return snapshot_id(list(candles), instrument_id, timeframe)
