"""ارزیاب شرط ورود/ابطال/انقضای سناریو روی داده بسته‌شده و تازه."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from fxars.config.settings import AnalysisSettings
from fxars.core.numerics import to_decimal
from fxars.core.timeutil import format_ts
from fxars.domain.enums import ScenarioStatus
from fxars.domain.models import Candle, Instrument, Scenario
from fxars.instruments.calendar import TradingCalendar


@dataclass(frozen=True)
class TriggerOutcome:
    to_status: ScenarioStatus | None
    event: str
    reason: str
    data_ref: str = ""

    @property
    def changed(self) -> bool:
        return self.to_status is not None


class TriggerEvaluator:
    def __init__(self, settings: AnalysisSettings, calendar: TradingCalendar | None = None) -> None:
        self.settings = settings
        self.calendar = calendar or TradingCalendar()

    def evaluate(self, scenario: Scenario, candles: list[Candle], now: datetime, instrument: Instrument) -> TriggerOutcome:
        if not candles:
            return TriggerOutcome(None, "no_data", "کندلی برای ارزیابی سناریو موجود نیست.")
        last = candles[-1]
        data_ref = f"{last.instrument_id}:{last.timeframe}:{format_ts(last.open_time)}"
        tf = last.timeframe

        if now >= scenario.expiry_at:
            return TriggerOutcome(ScenarioStatus.EXPIRED, "expired",
                                  f"زمان انقضای سناریو ({format_ts(scenario.expiry_at)}) رسیده است.", data_ref)

        if self.calendar.is_stale(last.available_at, now, tf, instrument_id=last.instrument_id,
                                  grace_seconds=300, max_age_bars=self.settings.max_evidence_age_bars):
            return TriggerOutcome(None, "stale_data", "داده بازار کهنه است؛ ارزیابی سناریو متوقف شد.", data_ref)


        # FIX-DUAL: invalidation_condition بازگردانده شد.
        if scenario.status in (ScenarioStatus.WATCH, ScenarioStatus.ARMED):
            condition = scenario.invalidation_condition or {}
            condition_type = condition.get("type")
            level = to_decimal(condition.get("level", "0"))
            if condition_type == "close_below" and last.close <= level:
                return TriggerOutcome(ScenarioStatus.INVALIDATED, "invalidated",
                                      f"شرط ابطال محقق شد: بسته‌شدن زیر {format(level, 'f')}.", data_ref)
            if condition_type == "close_above" and last.close >= level:
                return TriggerOutcome(ScenarioStatus.INVALIDATED, "invalidated",
                                      f"شرط ابطال محقق شد: بسته‌شدن بالای {format(level, 'f')}.", data_ref)
        entry = scenario.entry_condition or {}
        entry_type = entry.get("type")
        entry_level = to_decimal(entry.get("level", "0"))
        zone = scenario.entry_zone

        if scenario.status is ScenarioStatus.WATCH:
            proximity = (zone.width if zone else Decimal("0")) * Decimal("1.5") + Decimal("2") * instrument.pip_size
            distance = Decimal("0")
            if zone and not zone.contains(last.close):
                distance = min(abs(last.close - zone.low), abs(last.close - zone.high))
            if distance <= proximity:
                return TriggerOutcome(ScenarioStatus.ARMED, "preconditions_met",
                                      "قیمت به محدوده ورود نزدیک شد؛ سناریو مسلح شد.", data_ref)

        if scenario.status is ScenarioStatus.ARMED:
            triggered = False
            if entry_type == "price_cross_above":
                triggered = last.close > entry_level
            elif entry_type == "price_cross_below":
                triggered = last.close < entry_level
            elif entry_type == "zone_entry" and zone:
                triggered = last.low <= zone.high and last.high >= zone.low
            if triggered:
                return TriggerOutcome(ScenarioStatus.TRIGGERED, "triggered",
                                      f"شرط ورود محقق شد: بسته‌شدن در {format(last.close, 'f')}.", data_ref)

        if scenario.status is ScenarioStatus.TRIGGERED:
            lost = False
            if entry_type == "price_cross_above":
                lost = last.close < entry_level
            elif entry_type == "price_cross_below":
                lost = last.close > entry_level
            if lost:
                return TriggerOutcome(ScenarioStatus.EXPIRED, "entry_conditions_lost",
                                      "شرایط ورود از دست رفت؛ سناریو منقضی شد.", data_ref)

        return TriggerOutcome(None, "no_change", "شرایط گذار جدیدی محقق نشد.", data_ref)
