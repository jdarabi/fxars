"""سازنده سناریو: تبدیل تصمیم به شرط ورود، ابطال، حد ضرر، اهداف و انقضا."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from fxars.analysis.engine import AnalysisOutcome
from fxars.config.settings import AnalysisSettings
from fxars.core.ids import stable_id
from fxars.core.numerics import quantize
from fxars.core.timeutil import timeframe_delta
from fxars.domain.enums import DecisionAction, Direction, ScenarioStatus
from fxars.domain.models import Decision, PriceZone, Scenario
from fxars.instruments.calendar import TradingCalendar

MIN_STOP_PIPS = Decimal("3")


@dataclass(frozen=True)
class ScenarioBuildResult:
    scenario: Scenario | None
    reason: str = ""


class ScenarioBuilder:
    def __init__(self, settings: AnalysisSettings, calendar: TradingCalendar | None = None) -> None:
        self.settings = settings
        self.calendar = calendar or TradingCalendar()

    def build(
        self,
        outcome: AnalysisOutcome,
        decision: Decision,
        *,
        run_id: str,
        rules_version: str,
        tenant_id: str = "default",
    ) -> ScenarioBuildResult:
        if decision.action is DecisionAction.NO_TRADE or decision.direction is Direction.NEUTRAL:
            return ScenarioBuildResult(None, "NO_DIRECTIONAL_DECISION")
        if not outcome.candles:
            return ScenarioBuildResult(None, "NO_MARKET_DATA")
        instrument = outcome.instrument
        last = outcome.candles[-1]
        close = last.close
        atr_value = outcome.indicators.atr[-1]
        atr = Decimal(str(atr_value)) if atr_value else close * Decimal("0.0008")
        buffer = self.settings.stop_buffer_pips * instrument.pip_size
        structure = outcome.structure

        if decision.direction is Direction.LONG:
            reference = structure.last_swing_low.price if structure.last_swing_low else min(
                candle.low for candle in outcome.candles[-20:]
            )
            stop = reference - buffer
            minimum_stop = close - max(atr * Decimal("0.5"), MIN_STOP_PIPS * instrument.pip_size)
            if stop >= minimum_stop:
                stop = quantize(minimum_stop, instrument.digits)
            trigger = close + atr * Decimal("0.15")
        else:
            reference = structure.last_swing_high.price if structure.last_swing_high else max(
                candle.high for candle in outcome.candles[-20:]
            )
            stop = reference + buffer
            maximum_stop = close + max(atr * Decimal("0.5"), MIN_STOP_PIPS * instrument.pip_size)
            if stop <= maximum_stop:
                stop = quantize(maximum_stop, instrument.digits)
            trigger = close - atr * Decimal("0.15")

        stop = quantize(stop, instrument.digits)
        trigger = quantize(trigger, instrument.digits)
        risk_distance = abs(trigger - stop)
        if risk_distance < MIN_STOP_PIPS * instrument.pip_size:
            return ScenarioBuildResult(None, "STOP_DISTANCE_TOO_SMALL")
        if decision.direction is Direction.LONG and stop >= trigger:
            return ScenarioBuildResult(None, "INVALID_STOP_DIRECTION")
        if decision.direction is Direction.SHORT and stop <= trigger:
            return ScenarioBuildResult(None, "INVALID_STOP_DIRECTION")

        zone_half = atr * Decimal("0.25")
        entry_zone = PriceZone(low=quantize(trigger - zone_half, instrument.digits),
                               high=quantize(trigger + zone_half, instrument.digits))
        targets = []
        for ratio in self.settings.rr_targets:
            if decision.direction is Direction.LONG:
                price = trigger + risk_distance * ratio
            else:
                price = trigger - risk_distance * ratio
            targets.append({"type": "rr_multiple", "value": float(ratio), "price": format(quantize(price, instrument.digits), "f")})

        entry_condition = {
            "type": "price_cross_above" if decision.direction is Direction.LONG else "price_cross_below",
            "level": format(trigger, "f"),
            "timeframe": outcome.timeframe,
            "require_closed_candle": True,
        }
        invalidation_condition = {
            "type": "close_below" if decision.direction is Direction.LONG else "close_above",
            "level": format(stop, "f"),
            "timeframe": outcome.timeframe,
        }
        stop_logic = {
            "type": "structure_low" if decision.direction is Direction.LONG else "structure_high",
            "reference": "last_swing_low" if decision.direction is Direction.LONG else "last_swing_high",
            "level": format(stop, "f"),
            "buffer_pips": float(self.settings.stop_buffer_pips),
        }
        expiry_at = self._expiry(outcome)

        scenario_id = stable_id(
            "sc", outcome.instrument.instrument_id, outcome.timeframe, decision.direction.value,
            format(trigger, "f"), format(stop, "f"), outcome.as_of,
            "" if tenant_id == "default" else tenant_id, length=24,
        )
        scenario = Scenario(
            scenario_id=scenario_id,
            instrument_id=outcome.instrument.instrument_id,
            timeframe=outcome.timeframe,
            direction=decision.direction,
            status=ScenarioStatus.DRAFT,
            entry_condition=entry_condition,
            entry_zone=entry_zone,
            invalidation_condition=invalidation_condition,
            stop_logic=stop_logic,
            target_logic=tuple(targets),
            expiry_at=expiry_at,
            evidence_ids=decision.evidence_ids,
            analysis_run_id=run_id,
            decision_explanation=(
                f"تصمیم {decision.action.value} با امتیاز {decision.score:+.3f} و پوشش {decision.coverage:.0%}. "
                + "؛ ".join(decision.reasons[:2])
            ),
            created_at=outcome.as_of,
            updated_at=outcome.as_of,
            rules_version=rules_version,
            config_hash=outcome.config_hash,
            strength=decision.strength,
            tenant_id=tenant_id,
        )
        return ScenarioBuildResult(scenario, "CREATED")

    def _expiry(self, outcome: AnalysisOutcome):
        """انقضا بر مبنای کندل‌های معاملاتی، نه ساعت دیواری (تعطیلات/تعطیلی بازار)."""
        tf = timeframe_delta(outcome.timeframe)
        horizon = max(1, self.settings.scenario_expiry_bars)
        start = outcome.as_of + tf
        lookahead = tf * (horizon * 3) + timedelta(days=7)
        times = self.calendar.expected_bar_times(
            start, start + lookahead, outcome.timeframe,
            instrument_id=outcome.instrument.instrument_id,
        )
        if len(times) >= horizon:
            return times[horizon - 1] + tf
        return outcome.as_of + tf * horizon
