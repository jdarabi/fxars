"""سرویس قابلیت‌های اطلاعاتی تصمیم — اتصال به داده و مخازن.

این سرویس همان قابلیت‌های `fxars.decision.intelligence` را با داده واقعی
پروژه هماهنگ می‌کند و برای API/داشبورد قابل فراخوانی است.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fxars.config.settings import Settings
from fxars.decision.intelligence import (
    ChallengeService,
    DecisionJournal,
    premortem,
    replay_scenario,
    scenario_heatmap,
)
from fxars.storage.repositories import (
    AnalysisRepository,
    CandleRepository,
    InstrumentRepository,
    ScenarioRepository,
)


class IntelligenceService:
    def __init__(
        self,
        *,
        settings: Settings,
        clock: Callable[[], datetime],
        instruments: InstrumentRepository,
        candles: CandleRepository,
        scenarios: ScenarioRepository,
        analyses: AnalysisRepository,
        db,
        audit,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.instruments = instruments
        self.candles = candles
        self.scenarios = scenarios
        self.analyses = analyses
        self.db = db
        self.audit = audit
        self.journal = DecisionJournal(db, audit, clock)
        self.challenges = ChallengeService(db, audit, clock)

    # ------------------------------------------------------------------ دفتر تصمیم
    def journal_add(self, *, kind: str, body: str, actor: str, tenant_id: str = "default",
                    analysis_run_id: str | None = None, scenario_id: str | None = None,
                    decision_id: str | None = None, payload: dict[str, Any] | None = None) -> dict:
        entry = self.journal.add(
            kind=kind, body=body, actor=actor, tenant_id=tenant_id,
            analysis_run_id=analysis_run_id, scenario_id=scenario_id,
            decision_id=decision_id, payload=payload,
        )
        return entry.to_dict()

    def journal_list(self, *, tenant_id: str | None = "default", analysis_run_id: str | None = None,
                     scenario_id: str | None = None, limit: int = 200) -> list[dict]:
        return [
            entry.to_dict()
            for entry in self.journal.list(
                tenant_id=tenant_id, analysis_run_id=analysis_run_id,
                scenario_id=scenario_id, limit=limit,
            )
        ]

    # ------------------------------------------------------------------ بازپخش خلاف واقع
    def counterfactual(self, scenario_id: str, *, max_bars: int | None = None) -> dict[str, Any]:
        scenario = self.scenarios.get(scenario_id)
        instrument = self.instruments.get(scenario.instrument_id)
        try:
            source = self.instruments.primary_source(scenario.instrument_id, scenario.timeframe)
        except Exception:
            source = None
        series = self.candles.range(
            scenario.instrument_id, scenario.timeframe, source_id=source,
            as_of=self.clock(), closed_only=True,
        ) if source else []
        horizon = [candle for candle in series if candle.open_time >= scenario.created_at]
        bars = int(max_bars or self.settings.backtest.max_bars_in_trade)
        result = replay_scenario(
            scenario, horizon, pip_size=instrument.pip_size, max_bars=bars,
        )
        result["scenario_status"] = scenario.status.value
        result["decision_time"] = scenario.created_at.isoformat()
        return result

    # ------------------------------------------------------------------ پیش‌مرگ و نقشه حرارتی
    def premortem(self, run_id: str) -> dict[str, Any]:
        run = self.analyses.get_run(run_id)
        return {
            "run_id": run.run_id,
            "instrument_id": run.instrument_id,
            "timeframe": run.timeframe,
            "findings": premortem(run),
        }

    def heatmap(self, *, tenant_id: str | None = "default") -> dict[str, Any]:
        return scenario_heatmap(self.scenarios.live(tenant_id=tenant_id))

    # ------------------------------------------------------------------ چالش سناریو
    def challenge_add(self, scenario_id: str, *, thesis: str, actor: str,
                      evidence: list[str] | None = None, severity: str = "MEDIUM",
                      tenant_id: str = "default") -> dict[str, Any]:
        self.scenarios.get(scenario_id)
        challenge = self.challenges.add(
            scenario_id, thesis=thesis, actor=actor, evidence=tuple(evidence or ()),
            severity=severity, tenant_id=tenant_id,
        )
        return challenge.to_dict()

    def challenge_list(self, scenario_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.challenges.list(scenario_id, limit=limit)]
