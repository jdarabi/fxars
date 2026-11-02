"""Composition Root: ساخت و اتصال همه سرویس‌ها.

این کلاس تنها جایی است که زیرساخت به دامنه تزریق می‌شود؛ لایه‌های دامنه به SQLite
وابسته نیستند.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fxars.analysis.engine import AnalysisEngine
from fxars.audit.audit import AuditLog
from fxars.audit.outbox import Outbox
from fxars.config.settings import Settings
from fxars.core.timeutil import utcnow
from fxars.data.ingestion import IngestionResult, IngestionService
from fxars.data.quality import DataQualityEngine
from fxars.decision.scenario import ScenarioBuilder
from fxars.decision.state_machine import ScenarioStateMachine
from fxars.decision.trigger import TriggerEvaluator
from fxars.domain.enums import BacktestSegment, Role, ScenarioStatus
from fxars.domain.models import DataSource
from fxars.execution.paper_broker import PaperBroker
from fxars.execution.service import ExecutionService
from fxars.identity.service import IdentityService
from fxars.instruments.calendar import TradingCalendar, default_holidays
from fxars.instruments.spec import DEFAULT_SOURCE, default_instruments
from fxars.research.service import ResearchService
from fxars.research.walkforward import WalkForwardRunner
from fxars.risk.gate import RiskGate
from fxars.risk.killswitch import KillSwitch
from fxars.risk.service import RiskService
from fxars.services.analysis import AnalysisResult, AnalysisService
from fxars.services.scenarios import ScenarioEvaluation, ScenarioService
from fxars.storage.db import Database
from fxars.storage.repositories import (
    AccountRepository,
    AnalysisRepository,
    AuditRepository,
    BacktestRepository,
    CandleRepository,
    DataQualityRepository,
    EconomicEventRepository,
    IdempotencyRepository,
    InstrumentRepository,
    LockedTestRepository,
    LoginAttemptRepository,
    ModelRepository,
    OrderRepository,
    OutboxRepository,
    RawPayloadRepository,
    RiskRepository,
    ScenarioRepository,
    SessionRepository,
    SystemStateRepository,
    UserRepository,
)


class Platform:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        db: Database | None = None,
        clock: Callable[[], datetime] | None = None,
        calendar: TradingCalendar | None = None,
    ) -> None:
        self.settings = settings or Settings.load()
        self.clock = clock or utcnow
        self.db = db or Database(self.settings.db_path)
        self.db.migrate()
        self.calendar = calendar or TradingCalendar(default_holidays())

        self.instruments = InstrumentRepository(self.db)
        self.candles = CandleRepository(self.db)
        self.events = EconomicEventRepository(self.db)
        self.analyses = AnalysisRepository(self.db)
        self.scenarios = ScenarioRepository(self.db)
        self.decisions = RiskRepository(self.db)
        self.quality_runs = DataQualityRepository(self.db)
        self.backtests = BacktestRepository(self.db)
        self.accounts = AccountRepository(self.db)
        self.orders = OrderRepository(self.db)
        self.models = ModelRepository(self.db)
        self.locked_tests = LockedTestRepository(self.db)
        self.raw_payloads = RawPayloadRepository(self.db)
        self.users = UserRepository(self.db)
        self.sessions = SessionRepository(self.db)
        self.attempts = LoginAttemptRepository(self.db, clock=self.clock)
        self.idempotency = IdempotencyRepository(self.db)
        self.audit_repo = AuditRepository(self.db)
        self.outbox_repo = OutboxRepository(self.db)
        self.state = SystemStateRepository(self.db)

        self.audit = AuditLog(self.db)
        self.outbox = Outbox(self.db)
        self.killswitch = KillSwitch(self.state, self.audit, self.outbox, self.clock)
        self.quality = DataQualityEngine(self.settings.data_quality, self.calendar)
        self.ingestion = IngestionService(
            db=self.db, candles=self.candles, instruments=self.instruments,
            quality_runs=self.quality_runs, raw_payloads=self.raw_payloads,
            quality=self.quality, audit=self.audit, outbox=self.outbox,
        )
        self.analysis_engine = AnalysisEngine(self.settings.analysis, self.calendar)
        self.state_machine = ScenarioStateMachine(self.settings.rules_version)
        self.scenario_builder = ScenarioBuilder(self.settings.analysis, self.calendar)
        self.trigger = TriggerEvaluator(self.settings.analysis, self.calendar)

        self.analysis = AnalysisService(
            settings=self.settings, clock=self.clock, instruments=self.instruments, candles=self.candles,
            events=self.events, analyses=self.analyses, scenarios=self.scenarios, audit=self.audit,
            outbox=self.outbox, engine=self.analysis_engine, builder=self.scenario_builder,
            state_machine=self.state_machine, calendar=self.calendar,
        )
        self.scenario_service = ScenarioService(
            settings=self.settings, clock=self.clock, scenarios=self.scenarios, candles=self.candles,
            instruments=self.instruments, audit=self.audit, outbox=self.outbox,
            state_machine=self.state_machine, evaluator=self.trigger,
        )
        self.risk_gate = RiskGate(self.settings.risk, self.killswitch, self.calendar)
        self.risk = RiskService(
            settings=self.settings, clock=self.clock, gate=self.risk_gate, killswitch=self.killswitch,
            scenarios=self.scenarios, instruments=self.instruments, candles=self.candles,
            events=self.events, decisions=self.decisions, accounts=self.accounts,
            audit=self.audit, outbox=self.outbox, calendar=self.calendar,
        )
        self.identity = IdentityService(
            settings=self.settings, clock=self.clock, users=self.users, sessions=self.sessions,
            attempts=self.attempts, audit=self.audit,
        )
        self.research = ResearchService(
            settings=self.settings, clock=self.clock, instruments=self.instruments, candles=self.candles,
            events=self.events, backtests=self.backtests, locked_tests=self.locked_tests,
            engine=self.analysis_engine, audit=self.audit, outbox=self.outbox,
        )
        # FIX-05-PLATFORM-CALENDAR: calendar به ResearchService برای parity
        self.research._calendar = self.calendar
        self.walkforward = WalkForwardRunner(self.settings, self.research)
        self.execution = ExecutionService(
            settings=self.settings, clock=self.clock, scenarios=self.scenarios, decisions=self.decisions,
            orders=self.orders, killswitch=self.killswitch, audit=self.audit, outbox=self.outbox,
            broker=PaperBroker() if self.settings.execution_enabled else None,
        )

    # ------------------------------------------------------------------ راه‌اندازی
    def bootstrap(self, *, admin_password: str | None = None, analyst_password: str | None = None,
                  create_users: bool = True) -> dict[str, Any]:
        """ثبت نمادها/منبع داده و کاربران پایه؛ خروجی شامل اطلاعات یک‌بارمصرف است."""
        self.instruments.seed_defaults(default_instruments(), DataSource(**DEFAULT_SOURCE))
        self.instruments.save_source(DataSource(
            source_id="demo_ref", name="Demo Reference Feed", kind="synthetic", license_id="internal-demo",
            redistribution_allowed=False, retention_days=3650, priority=20, notes="سری مرجع بین‌بازاری",
        ))
        result: dict[str, Any] = {"instruments": len(self.instruments.list()), "users": []}
        if not create_users:
            return result
        if self.users.get_by_username("admin") is None:
            password = admin_password or secrets.token_urlsafe(12)
            user, secret = self.identity.create_user("admin", Role.ADMIN, password, totp_enabled=True,
                                                     display_name="مدیر سامانه")
            result["users"].append({"username": "admin", "password": password, "totp_secret": secret,
                                    "user_id": user.user_id})
        if self.users.get_by_username("analyst") is None:
            password = analyst_password or secrets.token_urlsafe(12)
            user, _ = self.identity.create_user("analyst", Role.ANALYST, password, totp_enabled=False,
                                                display_name="تحلیل‌گر")
            result["users"].append({"username": "analyst", "password": password, "user_id": user.user_id})
        if self.users.get_by_username("auditor") is None:
            password = secrets.token_urlsafe(12)
            self.identity.create_user("auditor", Role.AUDITOR, password, totp_enabled=False, display_name="حسابرس")
            result["users"].append({"username": "auditor", "password": password})
        return result

    # ------------------------------------------------------------------ داده
    def ingest_csv(self, path: str | Path, *, instrument_id: str, timeframe: str,
                   source_id: str = "demo_feed", now: datetime | None = None) -> IngestionResult:
        return self.ingestion.ingest_csv(path, instrument_id=instrument_id, source_id=source_id,
                                         timeframe=timeframe, now=now or self.clock())

    def ingest_candles(self, candles: list, *, instrument_id: str, source_id: str = "demo_feed") -> IngestionResult:
        return self.ingestion.ingest(candles, instrument_id=instrument_id, source_id=source_id, now=self.clock())

    def ingest_events(self, path: str | Path) -> int:
        from fxars.data.synthetic import read_events_csv

        events = read_events_csv(path)
        with self.db.transaction():
            for event in events:
                self.events.save(event)
        return len(events)

    # ------------------------------------------------------------------ تصمیم
    def run_analysis(self, instrument_id: str, timeframe: str, *, as_of: datetime | None = None,
                     actor: str = "system") -> AnalysisResult:
        return self.analysis.run(instrument_id, timeframe, as_of=as_of, actor=actor)

    def evaluate_scenario(self, scenario_id: str, *, now: datetime | None = None) -> ScenarioEvaluation:
        return self.scenario_service.evaluate(scenario_id, now=now or self.clock())

    def transition_scenario(self, scenario_id: str, status: ScenarioStatus, *, actor: str, reason: str) -> ScenarioEvaluation:
        return self.scenario_service.transition(scenario_id, status, actor=actor, reason=reason, now=self.clock())

    def evaluate_risk(self, scenario_id: str, account: Any, *, rates: dict[str, Any] | None = None,
                      now: datetime | None = None, actor: str = "system"):
        return self.risk.evaluate(scenario_id, account, rates=rates, now=now or self.clock(), actor=actor)

    def run_backtest(self, instrument_id: str, timeframe: str, *, overrides: dict[str, Any] | None = None,
                     segment: BacktestSegment = BacktestSegment.ALL, as_of: datetime | None = None,
                     actor: str = "system"):
        return self.research.run(instrument_id, timeframe, config_overrides=overrides or {},
                                 segment=segment, as_of=as_of, actor=actor)

    # ------------------------------------------------------------------ سیستم
    def audit_verify(self) -> dict[str, Any]:
        return self.audit.verify()

    def kill_switch_status(self) -> dict[str, Any]:
        return self.killswitch.status()

    def set_kill_switch(self, active: bool, *, actor: str, reason: str) -> dict[str, Any]:
        return self.killswitch.activate(actor=actor, reason=reason) if active else self.killswitch.deactivate(actor=actor, reason=reason)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Platform":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
