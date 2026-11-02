"""سرویس پژوهش: بک‌تست، ثبت نتایج، تحلیل حساسیت و PBO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Sequence

from fxars.analysis.engine import AnalysisEngine, AnalysisOutcome
from fxars.audit.audit import AuditAction, AuditLog
from fxars.audit.outbox import EventType, Outbox
from fxars.config.settings import Settings
from fxars.core.hashing import sha256_obj
from fxars.core.ids import stable_id
from fxars.core.timeutil import format_ts, utcnow
from fxars.data.snapshot import snapshot_id
from fxars.domain.enums import BacktestSegment, QualityStatus
from fxars.domain.models import BacktestRun, Candle, Instrument
from fxars.research.backtest import BacktestConfig, BacktestEngine, BacktestOutput, EvidenceTimeline
from fxars.research.metrics import compute_metrics, equity_returns
from fxars.research.overfitting import deflated_sharpe_ratio, probability_of_backtest_overfitting
from fxars.research.protocol import split_segments, segment_range, ValidationSplit
from fxars.storage.repositories import (
    BacktestRepository,
    CandleRepository,
    EconomicEventRepository,
    InstrumentRepository,
    LockedTestRepository,
)


@dataclass
class BacktestResult:
    run: BacktestRun
    output: BacktestOutput
    split: ValidationSplit | None = None


@dataclass
class ResearchContext:
    instrument: Instrument
    candles: list[Candle]
    outcome: AnalysisOutcome
    timeline: EvidenceTimeline
    snapshot: str


class ResearchService:
    def __init__(
        self,
        *,
        settings: Settings,
        clock: Callable[[], datetime],
        instruments: InstrumentRepository,
        candles: CandleRepository,
        events: EconomicEventRepository,
        backtests: BacktestRepository,
        locked_tests: LockedTestRepository,
        engine: AnalysisEngine,
        audit: AuditLog,
        outbox: Outbox,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.instruments = instruments
        self.candles = candles
        self.events = events
        self.backtests = backtests
        self.locked_tests = locked_tests
        self.engine = engine
        self.audit = audit
        self.outbox = outbox

    # ------------------------------------------------------------------ آماده‌سازی
    def prepare(self, instrument_id: str, timeframe: str, *, as_of: datetime | None = None) -> ResearchContext:
        instrument = self.instruments.get(instrument_id)
        # PRIMARY_SOURCE_RESEARCH: انتخاب منبع اصلی برای بک‌تست
        primary_source = self.instruments.primary_source(instrument_id, timeframe)
        candles = [
            candle for candle in self.candles.range(
                instrument_id, timeframe, source_id=primary_source, as_of=as_of, closed_only=True,
            )
            if candle.quality_status is not QualityStatus.INVALID
        ]
        if len(candles) < self.settings.analysis.min_bars + 20:
            raise ValueError(
                f"داده کافی برای بک‌تست وجود ندارد ({len(candles)} کندل؛ حداقل {self.settings.analysis.min_bars + 20})."
            )
        first, last_candle = candles[0].open_time, candles[-1]
        events = self.events.between(first - timedelta(days=2), last_candle.open_time + timedelta(days=2), as_of=None)
        references: dict[str, list[Candle]] = {}
        for reference_id in self.settings.analysis.intermarket_refs.get(instrument_id, []):
            reference = self.candles.range(reference_id, timeframe, as_of=last_candle.available_at, closed_only=True)
            if reference:
                references[reference_id] = reference
        snapshot = snapshot_id(candles, instrument_id, timeframe)
        run_id = stable_id("bt_input", instrument_id, timeframe, snapshot, self.settings.config_hash(), length=24)
        outcome = self.engine.analyze(
            instrument=instrument, timeframe=timeframe, candles=candles, as_of=last_candle.available_at,
            run_id=run_id, economic_events=events, references=references, config_hash=self.settings.config_hash(),
        )
        timeline = EvidenceTimeline(outcome.evidences, timeframe,
                                    max_age_bars=self.settings.analysis.max_evidence_age_bars)
        return ResearchContext(instrument=instrument, candles=candles, outcome=outcome, timeline=timeline, snapshot=snapshot)

    # ------------------------------------------------------------------ بک‌تست
    def run(
        self,
        instrument_id: str,
        timeframe: str,
        *,
        config: BacktestConfig | None = None,
        config_overrides: dict[str, Any] | None = None,
        segment: BacktestSegment = BacktestSegment.ALL,
        as_of: datetime | None = None,
        actor: str = "system",
        persist: bool = True,
        trials: int = 1,
    ) -> BacktestResult:
        context = self.prepare(instrument_id, timeframe, as_of=as_of)
        config = config or BacktestConfig.from_settings(
            self.settings.backtest, overrides=config_overrides,
            min_signal_strength=self.settings.risk.min_signal_strength,
        )
        split = split_segments(
            len(context.candles),
            train_fraction=self.settings.backtest.oos_train_fraction,
            validation_fraction=self.settings.backtest.oos_validation_fraction,
            embargo_bars=self.settings.backtest.embargo_bars,
        )
        chosen = segment_range(split, segment)
        start = max(chosen.start, self.settings.analysis.min_bars)
        # FIX-05-RESEARCH-CALENDAR: پاس دادن calendar برای parity کامل
        engine = BacktestEngine(context.instrument, timeframe, config, self.settings.analysis,
                                calendar=getattr(self, "_calendar", None))
        output = engine.simulate(context.candles, context.timeline, start_index=start, end_index=max(chosen.end, start + 2))
        metrics = dict(output.metrics)
        from fxars.core.numerics import annualization_factor
        metrics["deflated_sharpe"] = deflated_sharpe_ratio(
            equity_returns(output.equity_curve),
            trials=trials,
            periods_per_year=annualization_factor(timeframe),
        )
        metrics["stats"] = output.stats
        metrics["segment"] = segment.value
        run_id = stable_id(
            "bt", instrument_id, timeframe, config.hash(), context.snapshot, segment.value,
            self.settings.code_version, length=24,
        )
        started = self.clock()
        run = BacktestRun(
            run_id=run_id,
            instrument_id=instrument_id,
            timeframe=timeframe,
            config=config.to_dict(),
            config_hash=config.hash(),
            data_snapshot_id=context.snapshot,
            code_version=self.settings.code_version,
            segment=segment,
            started_at=started,
            finished_at=self.clock(),
            metrics=metrics,
            trades=tuple(output.trades),
            equity_curve=tuple((time, str(value)) for time, value in output.equity_curve),
            seed=config.seed,
        )
        if persist:
            with self.backtests.db.transaction():
                self.backtests.save(run)
                self.audit.append(
                    AuditAction.BACKTEST_COMPLETED, "backtest", run_id, actor=actor,
                    payload={
                        "instrument_id": instrument_id, "timeframe": timeframe, "segment": segment.value,
                        "trade_count": metrics.get("trade_count"), "net_profit": metrics.get("net_profit"),
                        "config_hash": run.config_hash, "data_snapshot_id": context.snapshot,
                    },
                )
                self.outbox.emit(
                    EventType.BACKTEST_COMPLETED,
                    {"run_id": run_id, "instrument_id": instrument_id, "timeframe": timeframe,
                     "trade_count": metrics.get("trade_count"), "net_profit": metrics.get("net_profit")},
                    occurred_at=run.finished_at,
                )
        return BacktestResult(run=run, output=output, split=split)

    # ------------------------------------------------------------------ PBO
    def run_variants(
        self,
        instrument_id: str,
        timeframe: str,
        variants: Sequence[dict[str, Any]],
        *,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        if len(variants) < 2:
            raise ValueError("برای PBO حداقل دو نسخه پارامتر لازم است.")
        context = self.prepare(instrument_id, timeframe, as_of=as_of)
        returns_matrix: list[list[float]] = []
        summaries: list[dict[str, Any]] = []
        for overrides in variants:
            config = BacktestConfig.from_settings(
                self.settings.backtest, overrides=dict(overrides),
                min_signal_strength=self.settings.risk.min_signal_strength,
            )
            engine = BacktestEngine(context.instrument, timeframe, config, self.settings.analysis)
            output = engine.simulate(
                context.candles, context.timeline,
                start_index=self.settings.analysis.min_bars, end_index=len(context.candles),
            )
            returns_matrix.append(equity_returns(output.equity_curve))
            summaries.append({
                "overrides": overrides,
                "metrics": {key: output.metrics[key] for key in ("net_profit", "trade_count", "sharpe", "max_drawdown_pct")},
            })
        result = probability_of_backtest_overfitting(returns_matrix)
        result["variants"] = summaries
        result["instrument_id"] = instrument_id
        result["timeframe"] = timeframe
        return result

    def record_locked_test_access(self, run_id: str, *, actor: str, purpose: str) -> None:
        from fxars.core.ids import new_id

        self.locked_tests.record(new_id("lta"), run_id, actor, purpose, self.clock())
        self.audit.append(
            AuditAction.LOCKED_TEST_OPENED, "backtest", run_id, actor=actor,
            payload={"purpose": purpose},
        )
