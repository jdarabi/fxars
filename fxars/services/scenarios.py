"""سرویس سناریو: ارزیابی شرط‌ها و گذارهای ثبت‌شده."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from fxars.audit.audit import AuditAction, AuditLog
from fxars.audit.outbox import EventType, Outbox
from fxars.config.settings import Settings
from fxars.core.context import current_correlation_id
from fxars.decision.state_machine import ScenarioStateMachine
from fxars.decision.trigger import TriggerEvaluator
from fxars.domain.enums import ScenarioStatus
from fxars.domain.models import Scenario, ScenarioTransition
from fxars.storage.repositories import (
    CandleRepository,
    InstrumentRepository,
    ScenarioRepository,
)


@dataclass
class ScenarioEvaluation:
    scenario: Scenario
    transition: ScenarioTransition | None
    reason: str


class ScenarioService:
    def __init__(
        self,
        *,
        settings: Settings,
        clock: Callable[[], datetime],
        scenarios: ScenarioRepository,
        candles: CandleRepository,
        instruments: InstrumentRepository,
        audit: AuditLog,
        outbox: Outbox,
        state_machine: ScenarioStateMachine,
        evaluator: TriggerEvaluator,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.scenarios = scenarios
        self.candles = candles
        self.instruments = instruments
        self.audit = audit
        self.outbox = outbox
        self.state_machine = state_machine
        self.evaluator = evaluator

    def evaluate(self, scenario_id: str, *, now: datetime | None = None, actor: str = "system") -> ScenarioEvaluation:
        scenario = self.scenarios.get(scenario_id)
        if scenario.status.is_terminal:
            return ScenarioEvaluation(scenario, None, "SCENARIO_TERMINAL")
        moment = now or self.clock()
        instrument = self.instruments.get(scenario.instrument_id)
        # FIX-DUAL: primary_source + فقط VALID
        try:
            primary_source = self.instruments.primary_source(
                scenario.instrument_id, scenario.timeframe,
            )
        except Exception:
            primary_source = None
        all_candles = self.candles.range(
            scenario.instrument_id, scenario.timeframe,
            source_id=primary_source, as_of=moment, closed_only=True,
        )
        from fxars.domain.enums import QualityStatus
        candles = [c for c in all_candles if c.quality_status is not QualityStatus.INVALID]
        outcome = self.evaluator.evaluate(scenario, candles, moment, instrument)
        if not outcome.changed:
            return ScenarioEvaluation(scenario, None, outcome.reason)
        updated, transition = self.state_machine.transition(
            scenario,
            outcome.to_status,
            actor=actor,
            reason=outcome.reason,
            occurred_at=moment,
            data_ref=outcome.data_ref,
            correlation_id=current_correlation_id(),
            event=outcome.event,
        )
        self._persist(updated, transition, actor=actor)
        return ScenarioEvaluation(updated, transition, outcome.reason)

    def transition(
        self,
        scenario_id: str,
        to_status: ScenarioStatus,
        *,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> ScenarioEvaluation:
        scenario = self.scenarios.get(scenario_id)
        moment = now or self.clock()
        updated, transition = self.state_machine.transition(
            scenario,
            to_status,
            actor=actor,
            reason=reason,
            occurred_at=moment,
            correlation_id=current_correlation_id(),
        )
        self._persist(updated, transition, actor=actor)
        return ScenarioEvaluation(updated, transition, reason)

    def _persist(self, scenario: Scenario, transition: ScenarioTransition, *, actor: str) -> None:
        with self.scenarios.db.transaction():
            self.scenarios.save(scenario)
            self.scenarios.add_transition(transition)
            self.audit.append(
                AuditAction.SCENARIO_TRANSITION,
                "scenario",
                scenario.scenario_id,
                actor=actor,
                correlation_id=transition.correlation_id,
                payload={
                    "from": transition.from_status.value,
                    "to": transition.to_status.value,
                    "event": transition.event,
                    "reason": transition.reason,
                    "rules_version": transition.rules_version,
                },
            )
            self.outbox.emit(
                EventType.SCENARIO_TRANSITIONED,
                {
                    "scenario_id": scenario.scenario_id,
                    "from": transition.from_status.value,
                    "to": transition.to_status.value,
                    "event": transition.event,
                    "occurred_at": transition.occurred_at.isoformat(),
                },
                occurred_at=transition.occurred_at,
            )
