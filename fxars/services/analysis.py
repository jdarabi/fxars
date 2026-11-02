"""سرویس اجرای تحلیل: داده → شواهد → تصمیم → سناریو → ثبت و ممیزی."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Callable

from fxars.analysis.engine import AnalysisEngine, AnalysisOutcome
from fxars.audit.audit import AuditAction, AuditLog
from fxars.audit.outbox import EventType, Outbox
from fxars.config.settings import Settings
from fxars.core.context import current_correlation_id
from fxars.core.hashing import sha256_obj
from fxars.core.ids import stable_id
from fxars.core.timeutil import format_ts, timeframe_delta, utcnow
from fxars.data.snapshot import snapshot_id
from fxars.decision.aggregation import aggregate_evidence
from fxars.decision.scenario import ScenarioBuilder
from fxars.decision.state_machine import ScenarioStateMachine
from fxars.domain.enums import AnalysisStatus, DecisionAction, Direction, QualityStatus, ScenarioStatus, Timeframe
from fxars.domain.models import (
    AnalysisRun,
    Decision,
    Evidence,
    Scenario,
    ScenarioTransition,
)
from fxars.instruments.calendar import TradingCalendar
from fxars.storage.repositories import (
    AnalysisRepository,
    CandleRepository,
    EconomicEventRepository,
    InstrumentRepository,
    ScenarioRepository,
)


@dataclass
class AnalysisResult:
    run: AnalysisRun
    outcome: AnalysisOutcome | None
    evidences: list[Evidence]
    decision: Decision
    scenario: Scenario | None
    scenario_reason: str = ""


class AnalysisService:
    def __init__(
        self,
        *,
        settings: Settings,
        clock: Callable[[], datetime],
        instruments: InstrumentRepository,
        candles: CandleRepository,
        events: EconomicEventRepository,
        analyses: AnalysisRepository,
        scenarios: ScenarioRepository,
        audit: AuditLog,
        outbox: Outbox,
        engine: AnalysisEngine,
        builder: ScenarioBuilder,
        state_machine: ScenarioStateMachine,
        calendar: TradingCalendar,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.instruments = instruments
        self.candles = candles
        self.events = events
        self.analyses = analyses
        self.scenarios = scenarios
        self.audit = audit
        self.outbox = outbox
        self.engine = engine
        self.builder = builder
        self.state_machine = state_machine
        self.calendar = calendar

    def run(
        self,
        instrument_id: str,
        timeframe: str,
        *,
        as_of: datetime | None = None,
        actor: str = "system",
    ) -> AnalysisResult:
        instrument = self.instruments.get(instrument_id)
        tf = Timeframe.parse(timeframe)
        moment = as_of or self.clock()
        correlation = current_correlation_id()
        started_at = self.clock()

        # PRIMARY_SOURCE_ANALYSIS: تحلیل فقط روی منبع اصلی انجام می‌شود.
        primary_source = self.instruments.primary_source(instrument_id, tf.value)
        candles = [
            candle
            for candle in self.candles.range(
                instrument_id, tf.value, source_id=primary_source, as_of=moment, closed_only=True,
            )
            if candle.quality_status is not QualityStatus.INVALID
        ]
        latest = candles[-1] if candles else None
        decision_time = latest.available_at if latest else moment
        stale = bool(
            latest
            and self.calendar.is_stale(
                latest.available_at, moment, tf.value,
                grace_seconds=self.settings.data_quality.freshness_grace_seconds,
                max_age_bars=self.settings.data_quality.max_bar_age_bars,
            )
        )
        snapshot = snapshot_id(candles, instrument_id, tf.value)
        run_basis = decision_time if (latest and not stale) else moment
        run_id = stable_id(
            "ar", instrument_id, tf.value, snapshot, self.settings.config_hash(),
            self.settings.code_version, run_basis, length=24,
        )
        data_quality = {
            "bars": len(candles),
            "stale": stale,
            "latest_bar": format_ts(latest.open_time) if latest else None,
            "latest_available_at": format_ts(latest.available_at) if latest else None,
            "latest_quality": latest.quality_status.value if latest else None,
            "snapshot_id": snapshot,
            "requested_as_of": format_ts(moment),
            "decision_time": format_ts(decision_time),
        }

        if latest is None or len(candles) < self.settings.analysis.min_bars:
            decision = Decision(
                action=DecisionAction.NO_TRADE,
                direction=Direction.NEUTRAL,
                score=0.0,
                confidence_raw=0.0,
                family_scores={},
                conflicts=(),
                coverage=0.0,
                stability=0.0,
                reasons=("داده کافی برای تحلیل وجود ندارد.",),
                evidence_ids=(),
                no_trade_reason="NO_DATA" if latest is None else "INSUFFICIENT_DATA",
            )
            return self._persist(
                instrument_id=instrument_id, timeframe=tf.value, moment=decision_time, run_id=run_id,
                snapshot=snapshot, data_quality=data_quality, decision=decision, evidences=[],
                outcome=None, scenario=None, scenario_reason="NO_ANALYSIS",
                status=AnalysisStatus.NO_TRADE, started_at=started_at, actor=actor,
                correlation=correlation, stale=stale,
            )

        if stale:
            decision = Decision(
                action=DecisionAction.NO_TRADE,
                direction=Direction.NEUTRAL,
                score=0.0,
                confidence_raw=0.0,
                family_scores={},
                conflicts=(),
                coverage=0.0,
                stability=0.0,
                reasons=(
                    "داده بازار کهنه است؛ طبق اصل Fail-Safe خروجی NO TRADE است.",
                    f"آخرین کندل در {format_ts(latest.open_time)} باز شده و در {format_ts(latest.available_at)} در دسترس بوده است.",
                ),
                evidence_ids=(),
                no_trade_reason="DATA_STALE",
            )
            return self._persist(
                instrument_id=instrument_id, timeframe=tf.value, moment=decision_time, run_id=run_id,
                snapshot=snapshot, data_quality=data_quality, decision=decision, evidences=[],
                outcome=None, scenario=None, scenario_reason="DATA_STALE",
                status=AnalysisStatus.STALE, started_at=started_at, actor=actor,
                correlation=correlation, stale=True,
            )

        lookback = self.settings.analysis.fundamental_lookback_hours
        events = self.events.between(
            decision_time - timedelta(hours=lookback),
            decision_time + timedelta(days=2),
            as_of=decision_time,
        )
        references = self._references(instrument_id, tf.value, decision_time)

        outcome = self.engine.analyze(
            instrument=instrument,
            timeframe=tf.value,
            candles=candles,
            as_of=decision_time,
            run_id=run_id,
            economic_events=events,
            references=references,
            config_hash=self.settings.config_hash(),
        )
        outcome.data_quality = data_quality
        if outcome.status != "COMPLETED":
            decision = Decision(
                action=DecisionAction.NO_TRADE,
                direction=Direction.NEUTRAL,
                score=0.0,
                confidence_raw=0.0,
                family_scores={},
                conflicts=(),
                coverage=0.0,
                stability=0.0,
                reasons=(outcome.reason or "تحلیل قابل اجرا نبود.",),
                evidence_ids=(),
                no_trade_reason="INSUFFICIENT_DATA",
            )
            return self._persist(
                instrument_id=instrument_id, timeframe=tf.value, moment=decision_time, run_id=run_id,
                snapshot=snapshot, data_quality=data_quality, decision=decision, evidences=[],
                outcome=outcome, scenario=None, scenario_reason="INSUFFICIENT_DATA",
                status=AnalysisStatus.NO_TRADE, started_at=started_at, actor=actor,
                correlation=correlation, stale=False,
            )

        decision = aggregate_evidence(outcome.evidences, self.settings.analysis, as_of=decision_time, timeframe=tf.value)
        scenario: Scenario | None = None
        scenario_reason = "NO_TRADE"
        transition: ScenarioTransition | None = None

        if decision.action is not DecisionAction.NO_TRADE:
            built = self.builder.build(outcome, decision, run_id=run_id, rules_version=self.settings.rules_version)
            scenario_reason = built.reason
            if built.scenario is None:
                decision = replace(
                    decision,
                    action=DecisionAction.NO_TRADE,
                    direction=Direction.NEUTRAL,
                    no_trade_reason=f"SCENARIO_{built.reason}",
                    reasons=decision.reasons + (f"ساخت سناریو ناموفق: {built.reason}",),
                )
            else:
                scenario = built.scenario
                if decision.strength >= self.settings.risk.min_signal_strength:
                    scenario, transition = self.state_machine.transition(
                        scenario, ScenarioStatus.WATCH, actor="system",
                        reason=(
                            f"شواهد کافی: امتیاز {decision.score:+.3f}، پوشش {decision.coverage:.0%}، "
                            f"پایداری {decision.stability:.0%}."
                        ),
                        occurred_at=decision_time,
                        data_ref=f"{instrument_id}:{tf.value}:{format_ts(latest.open_time)}",
                        correlation_id=correlation,
                    )

        retention_bars = max(24, self.settings.analysis.max_evidence_age_bars * 4)
        cutoff = decision_time - timeframe_delta(tf.value) * retention_bars
        stored = [evidence for evidence in outcome.evidences if evidence.available_at >= cutoff]

        status = AnalysisStatus.COMPLETED if decision.action is not DecisionAction.NO_TRADE else AnalysisStatus.NO_TRADE
        return self._persist(
            instrument_id=instrument_id, timeframe=tf.value, moment=decision_time, run_id=run_id,
            snapshot=snapshot, data_quality=data_quality, decision=decision, evidences=stored,
            outcome=outcome, scenario=scenario, scenario_reason=scenario_reason,
            status=status, started_at=started_at, actor=actor, correlation=correlation,
            stale=False, transition=transition,
        )

    def _references(self, instrument_id: str, timeframe: str, moment: datetime) -> dict[str, list]:
        references: dict[str, list] = {}
        for reference_id in self.settings.analysis.intermarket_refs.get(instrument_id, []):
            try:
                ref_source = self.instruments.primary_source(reference_id, timeframe)
            except Exception:
                continue
            candles = self.candles.range(
                reference_id, timeframe, source_id=ref_source, as_of=moment, closed_only=True,
            )
            if candles:
                references[reference_id] = candles
        return references

    def _persist(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        moment: datetime,
        run_id: str,
        snapshot: str,
        data_quality: dict,
        decision: Decision,
        evidences: list[Evidence],
        outcome: AnalysisOutcome | None,
        scenario: Scenario | None,
        scenario_reason: str,
        status: AnalysisStatus,
        started_at: datetime,
        actor: str,
        correlation: str,
        stale: bool,
        transition: ScenarioTransition | None = None,
    ) -> AnalysisResult:
        finished = self.clock()
        # ترتیب/شناسه شواهد بخشی از هویت نتیجه نیست؛ هش بر تصمیم + امضای معنایی شواهد است.
        evidences = sorted(evidences, key=lambda evidence: evidence.evidence_id)
        # FIX-13-RESULT-HASH: امضای کامل Evidence
        signature = sorted(
            (
                {
                    "module_id": evidence.module_id,
                    "module_version": evidence.module_version,
                    "family": evidence.family.value,
                    "observed_at": format_ts(evidence.observed_at),
                    "available_at": format_ts(evidence.available_at),
                    "direction": evidence.direction.value,
                    "strength": evidence.strength,
                    "confidence_raw": evidence.confidence_raw,
                    "price_zone": (
                        {"low": format(evidence.price_zone.low, "f"),
                         "high": format(evidence.price_zone.high, "f")}
                        if evidence.price_zone else None
                    ),
                    "invalidation": evidence.invalidation,
                    "expiry": format_ts(evidence.expiry) if evidence.expiry else None,
                    "parameters_hash": evidence.parameters_hash,
                    "source_refs": list(evidence.source_refs),
                }
                for evidence in evidences
            ),
            key=lambda item: (item["observed_at"], item["module_id"], item["direction"], item["strength"]),
        )
        result_hash = sha256_obj(
            {
                "decision": decision.to_dict(),
                "evidence_signature": signature,
            }
        )
        existing = self.analyses.find_run(run_id)
        if existing is not None and existing.result_hash != result_hash:
            from fxars.core.errors import ReproducibilityError

            raise ReproducibilityError(
                "اجرای دوباره با همان ورودی، خروجی متفاوتی تولید کرد.",
                details={
                    "run_id": run_id,
                    "existing_hash": existing.result_hash,
                    "new_hash": result_hash,
                    "decision_hash": sha256_obj(decision.to_dict()),
                    "evidence_hash": sha256_obj([evidence.to_dict() for evidence in evidences]),
                    "evidence_count": len(evidences),
                    "action": decision.action.value,
                    "score": decision.score,
                },
            )

        if existing is not None and existing.result_hash == result_hash:
            stored_evidence = self.analyses.evidence_for(run_id)
            stored_scenario = self.scenarios.find_by_run(run_id)
            return AnalysisResult(
                run=existing,
                outcome=outcome,
                evidences=stored_evidence if stored_evidence else evidences,
                decision=decision,
                scenario=stored_scenario if stored_scenario else scenario,
                scenario_reason=scenario_reason,
            )

        if existing is not None and existing.result_hash == result_hash:
            stored_evidence = self.analyses.evidence_for(run_id)
            stored_scenario = self.scenarios.find_by_run(run_id)
            return AnalysisResult(
                run=existing,
                outcome=outcome,
                evidences=stored_evidence if stored_evidence else evidences,
                decision=decision,
                scenario=stored_scenario if stored_scenario else scenario,
                scenario_reason=scenario_reason,
            )

        decision_payload = decision.to_dict()
        decision_payload["scenario_id"] = scenario.scenario_id if scenario else None
        decision_payload["scenario_reason"] = scenario_reason

        run = AnalysisRun(
            run_id=run_id,
            instrument_id=instrument_id,
            timeframe=timeframe,
            as_of=moment,
            data_snapshot_id=snapshot,
            config_hash=self.settings.config_hash(),
            code_version=self.settings.code_version,
            model_version="none",
            status=status,
            correlation_id=correlation,
            started_at=existing.started_at if existing else started_at,
            finished_at=finished,
            result_hash=result_hash,
            evidence_count=len(evidences),
            decision=decision_payload,
            data_quality=data_quality,
            error=None,
        )

        with self.analyses.db.transaction():
            self.analyses.save_run(run)
            if evidences:
                self.analyses.add_evidence(evidences)
            if scenario is not None:
                self.scenarios.save(scenario)
            if transition is not None:
                self.scenarios.add_transition(transition)
            self.audit.append(
                AuditAction.ANALYSIS_COMPLETED if status is AnalysisStatus.COMPLETED else AuditAction.ANALYSIS_NO_TRADE,
                "analysis_run",
                run_id,
                actor=actor,
                correlation_id=correlation,
                payload={
                    "instrument_id": instrument_id,
                    "timeframe": timeframe,
                    "status": status.value,
                    "decision": decision.action.value,
                    "score": decision.score,
                    "coverage": decision.coverage,
                    "stability": decision.stability,
                    "no_trade_reason": decision.no_trade_reason,
                    "scenario_id": scenario.scenario_id if scenario else None,
                    "data_snapshot_id": snapshot,
                    "stale": stale,
                },
            )
            self.outbox.emit(
                EventType.ANALYSIS_COMPLETED,
                {
                    "run_id": run_id,
                    "instrument_id": instrument_id,
                    "timeframe": timeframe,
                    "status": status.value,
                    "decision": decision.action.value,
                    "scenario_id": scenario.scenario_id if scenario else None,
                    "data_snapshot_id": snapshot,
                },
                occurred_at=finished,
            )
            if scenario is not None:
                self.outbox.emit(
                    EventType.SCENARIO_CREATED,
                    {
                        "scenario_id": scenario.scenario_id,
                        "instrument_id": scenario.instrument_id,
                        "direction": scenario.direction.value,
                        "status": scenario.status.value,
                        "entry_condition": scenario.entry_condition,
                        "expiry_at": format_ts(scenario.expiry_at),
                    },
                    occurred_at=finished,
                )

        return AnalysisResult(
            run=run,
            outcome=outcome,
            evidences=evidences,
            decision=decision,
            scenario=scenario,
            scenario_reason=scenario_reason,
        )
