"""Composition Root: ساخت و اتصال همه سرویس‌ها.

این کلاس تنها جایی است که زیرساخت به دامنه تزریق می‌شود؛ لایه‌های دامنه به SQLite
وابسته نیستند.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

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
from fxars.domain.enums import BacktestSegment, Phase, Role, ScenarioStatus
from fxars.domain.models import DataSource
from fxars.execution.approval import ApprovalService
from fxars.execution.service import ExecutionService
from fxars.governance.models import ModelRegistryService
from fxars.governance.policy import PolicyRegistry
from fxars.governance.provenance import DecisionProvenanceStore, ProvenanceService
from fxars.identity.service import IdentityService
from fxars.instruments.calendar import (
    TradingCalendar,
    default_early_closes,
    default_holidays,
    default_metal_holidays,
)
from fxars.instruments.spec import DEFAULT_SOURCE, default_instruments
from fxars.research.service import ResearchService
from fxars.research.walkforward import WalkForwardRunner
from fxars.risk.gate import RiskGate
from fxars.risk.killswitch import KillSwitch
from fxars.risk.lock_lifecycle import RiskLockMachine, RiskLockThresholds
from fxars.risk.service import RiskService
from fxars.services.analysis import AnalysisResult, AnalysisService
from fxars.services.intelligence import IntelligenceService
from fxars.services.scenarios import ScenarioEvaluation, ScenarioService
from fxars.services.strategy import StrategyExecutionService
from fxars.storage.db import Database
from fxars.storage.repositories import (
    AccountRepository,
    AnalysisRepository,
    ApprovalRepository,
    AuditRepository,
    BacktestRepository,
    CandleRepository,
    ClosedTradeRepository,
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
    TenantRepository,
    UserRepository,
)
from fxars.tenancy.quota import QuotaService
from fxars.tenancy.rights import DataRightsService


def _select_broker(settings):
    """Select broker based on phase (READ_ONLY/PAPER/DEMO/AUTOMATED_LIMITED)."""
    from fxars.domain.enums import Phase
    if not settings.execution_enabled:
        return None
    phase = settings.phase
    if phase is Phase.PAPER:
        from fxars.execution.paper_broker import PaperBroker
        return PaperBroker()
    if phase in (Phase.DEMO, Phase.ASSISTED, Phase.AUTOMATED_LIMITED):
        try:
            from fxars.execution.mt5_broker import MT5Broker
            return MT5Broker()
        except Exception as exc:
            from fxars.core.logging_setup import get_logger
            get_logger("platform").warning(
                "MT5Broker unavailable; falling back to PaperBroker",
                extra={"data": {"error": str(exc)}},
            )
            from fxars.execution.paper_broker import PaperBroker
            return PaperBroker()
    return None


class Platform:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        db: Database | None = None,
        clock: Callable[[], datetime] | None = None,
        calendar: TradingCalendar | None = None,
        sync_phase: bool = True,
    ) -> None:
        self.settings = settings or Settings.load()
        from fxars.config.settings import PROJECT_ROOT, PhaseSettings
        self.phase_path = PROJECT_ROOT / "config" / "phase.json"
        self.phase_settings = PhaseSettings.load(self.phase_path)
        self._phase_lock = threading.Lock()
        # FIX-DUAL-SYNC-PHASE: settings.phase باید با phase.json.mode هم‌خوان شود
        if sync_phase:
            try:
                from dataclasses import replace as _replace

                from fxars.domain.enums import Phase as _Phase
                _ui_mode = self.phase_settings.mode
                if _ui_mode == "ADVISOR":
                    self.settings = _replace(self.settings, phase=_Phase.READ_ONLY)
                elif _ui_mode == "AUTOMATED_LIMITED":
                    if self.phase_settings.automated_limited.enabled:
                        self.settings = _replace(self.settings, phase=_Phase.AUTOMATED_LIMITED)
                    else:
                        self.settings = _replace(self.settings, phase=_Phase.READ_ONLY)
                elif _ui_mode in {"READ_ONLY", "PAPER", "DEMO", "ASSISTED"}:
                    self.settings = _replace(self.settings, phase=_Phase(_ui_mode))
            except Exception as _exc:
                from fxars.core.logging_setup import get_logger
                get_logger("platform").warning(
                    "phase sync failed: %s", _exc, extra={"data": {"ui_mode": _ui_mode}},
                )
        self.clock = clock or utcnow
        from fxars.security.kms import build_key_provider

        self.kms = build_key_provider(self.settings)
        if db is not None:
            self.db = db
        else:
            # FIX-10-PG: انتخاب backend از settings (sqlite | postgres)
            from fxars.storage.factory import create_database
            self.db = create_database(self.settings)
        self.db.migrate()
        self.calendar = calendar or TradingCalendar(
            default_holidays(),
            early_closes=default_early_closes(),
            metal_holidays=default_metal_holidays(),
        )

        self.instruments = InstrumentRepository(self.db)
        self.candles = CandleRepository(self.db)
        self.events = EconomicEventRepository(self.db)
        self.analyses = AnalysisRepository(self.db)
        self.scenarios = ScenarioRepository(self.db)
        self.tenants = TenantRepository(self.db)
        self.decisions = RiskRepository(self.db)
        self.quality_runs = DataQualityRepository(self.db)
        self.backtests = BacktestRepository(self.db)
        self.accounts = AccountRepository(self.db)
        self.orders = OrderRepository(self.db)
        self.closed_trades = ClosedTradeRepository(self.db)
        self.approvals = ApprovalRepository(self.db)
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
        self.quota = QuotaService(
            tenants=self.tenants, users=self.users, analyses=self.analyses,
            scenarios=self.scenarios, clock=self.clock,
        )
        self.data_rights = DataRightsService(
            analyses=self.analyses, scenarios=self.scenarios, decisions=self.decisions,
            orders=self.orders, users=self.users, clock=self.clock,
        )
        self.killswitch = KillSwitch(self.state, self.audit, self.outbox, self.clock)
        # SUPPLEMENT-1.1: حاکمیت، منشأ تصمیم و قفل ریسک
        self.policy_registry = PolicyRegistry(self.db, self.audit, self.clock)
        self.provenance_store = DecisionProvenanceStore(self.db)
        self.provenance = ProvenanceService(self.provenance_store, self.audit, self.outbox)
        self.model_registry = ModelRegistryService(
            self.models, self.db, self.audit,
            policy=self.settings.decision.governance, clock=self.clock,
        )
        self.risk_lock = RiskLockMachine(
            self.state, self.audit, clock=self.clock,
            thresholds=RiskLockThresholds.from_risk_policy(self.settings.risk),
        )
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
            quality_runs=self.quality_runs, quota=self.quota, provenance=self.provenance,
        )
        self.scenario_service = ScenarioService(
            settings=self.settings, clock=self.clock, scenarios=self.scenarios, candles=self.candles,
            instruments=self.instruments, audit=self.audit, outbox=self.outbox,
            state_machine=self.state_machine, evaluator=self.trigger,
        )
        self.intelligence = IntelligenceService(
            settings=self.settings, clock=self.clock, instruments=self.instruments,
            candles=self.candles, scenarios=self.scenarios, analyses=self.analyses,
            db=self.db, audit=self.audit,
        )
        self.risk_gate = RiskGate(
            self.settings.risk, self.killswitch, self.calendar,
            risk_lock=lambda: self.risk_lock.current().blocks_orders,
        )
        self.risk = RiskService(
            settings=self.settings, clock=self.clock, gate=self.risk_gate, killswitch=self.killswitch,
            scenarios=self.scenarios, instruments=self.instruments, candles=self.candles,
            events=self.events, decisions=self.decisions, accounts=self.accounts,
            audit=self.audit, outbox=self.outbox, calendar=self.calendar,
            orders=self.orders, trades=self.closed_trades, risk_lock=self.risk_lock,
        )
        self.identity = IdentityService(
            settings=self.settings, clock=self.clock, users=self.users, sessions=self.sessions,
            attempts=self.attempts, audit=self.audit, tenants=self.tenants, quota=self.quota,
            key_provider=self.kms,
        )
        self.research = ResearchService(
            settings=self.settings, clock=self.clock, instruments=self.instruments, candles=self.candles,
            events=self.events, backtests=self.backtests, locked_tests=self.locked_tests,
            engine=self.analysis_engine, audit=self.audit, outbox=self.outbox,
        )
        # FIX-05-PLATFORM-CALENDAR: calendar به ResearchService برای parity
        self.research._calendar = self.calendar  # type: ignore[attr-defined]
        self.walkforward = WalkForwardRunner(self.settings, self.research)
        self.approval_service = ApprovalService(
            approvals=self.approvals, orders=self.orders, clock=self.clock, audit=self.audit,
            ttl_seconds=self.settings.risk.decision_ttl_seconds,
        )
        self.execution = ExecutionService(
            settings=self.settings, clock=self.clock, scenarios=self.scenarios, decisions=self.decisions,
            orders=self.orders, killswitch=self.killswitch, audit=self.audit, outbox=self.outbox,
            broker=_select_broker(self.settings), approvals=self.approval_service,
            scenario_gate=self._scenario_trigger_required,
        )
        from fxars.execution.attribution import AttributionService
        from fxars.execution.close_reconciliation import CloseReconciliationService
        self.close_reconciliation = CloseReconciliationService(
            orders=self.orders, trades=self.closed_trades, analyses=self.analyses,
            scenarios=self.scenarios, decisions=self.decisions, candles=self.candles,
            audit=self.audit, outbox=self.outbox, broker=self.execution.broker,
            clock=self.clock,
        )
        self.attribution = AttributionService(self.closed_trades)
        self.strategy_execution = StrategyExecutionService(
            settings=self.settings,
            phase_settings=self.phase_settings,
            clock=self.clock,
            instruments=self.instruments,
            scenarios=self.scenarios,
            orders=self.orders,
            risk=self.risk,
            execution=self.execution,
            approvals=self.approval_service,
            audit=self.audit,
            broker_is_real=lambda: (
                getattr(getattr(self.execution, "broker", None), "name", "") == "mt5"
            ),
            quota=self.quota,
        )

        # FIX-08-OUTBOX-CONSUMER: ثبت consumerهای پیش‌فرض
        from fxars.audit.handlers import ConsumerStats, default_handlers
        self.outbox_stats = ConsumerStats()
        self.outbox_handlers = default_handlers(stats=self.outbox_stats)

    # ------------------------------------------------------------------ راه‌اندازی
    def bootstrap(self, *, admin_password: str | None = None, analyst_password: str | None = None,
                  create_users: bool = True) -> dict[str, Any]:
        """ثبت نمادها/منبع داده و کاربران پایه؛ خروجی شامل اطلاعات یک‌بارمصرف است."""
        self.instruments.seed_defaults(default_instruments(), DataSource(**DEFAULT_SOURCE))  # type: ignore[arg-type]
        self.instruments.save_source(DataSource(
            source_id="demo_ref", name="Demo Reference Feed", kind="synthetic", license_id="internal-demo",
            redistribution_allowed=False, retention_days=3650, priority=20, notes="سری مرجع بین‌بازاری",
        ))
        self.instruments.save_source(DataSource(
            source_id="mt5", name="MetaTrader 5 Broker Feed", kind="broker", license_id="broker-terms",
            redistribution_allowed=False, retention_days=3650, priority=5,
            notes="داده زنده/تاریخی بروکر؛ زمان‌ها UTC و مطابق شرایط کارگزار.",
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

    # ------------------------------------------------------------------ فاز
    def apply_phase(self, mode: str, *, automated_enabled: bool | None = None,
                    persist: bool = True) -> dict[str, Any]:
        """اعمال فوری فاز در زمان اجرا و همگام‌سازی همه سرویس‌ها.

        بدون این همگام‌سازی، POST روی /api/v1/phase فقط فایل را عوض می‌کرد و
        settings/services/broker تا ری‌استارت بعدی روی فاز قبلی می‌ماندند.
        """
        from dataclasses import replace as _replace

        from fxars.config.settings import PhaseSettings
        from fxars.domain.enums import Phase as _Phase

        normalized = str(mode or "").strip().upper()
        allowed = {"ADVISOR", "AUTOMATED_LIMITED", "READ_ONLY", "PAPER", "DEMO", "ASSISTED"}
        if normalized not in allowed:
            raise ValueError(f"فاز نامعتبر است: {mode}")

        with self._phase_lock:
            phase_settings = PhaseSettings.load(self.phase_path)
            if normalized == "AUTOMATED_LIMITED" and automated_enabled is not None:
                phase_settings = _replace(
                    phase_settings,
                    automated_limited=_replace(
                        phase_settings.automated_limited, enabled=bool(automated_enabled),
                    ),
                )
            phase_settings = _replace(phase_settings, mode=normalized)

            if normalized == "ADVISOR":
                target = _Phase.READ_ONLY
            elif normalized == "AUTOMATED_LIMITED":
                target = (
                    _Phase.AUTOMATED_LIMITED
                    if phase_settings.automated_limited.enabled
                    else _Phase.READ_ONLY
                )
            else:
                target = _Phase(normalized)

            previous = self.settings.phase
            new_settings = _replace(self.settings, phase=target)
            old_broker = self.execution.broker
            new_broker = old_broker
            if target is not previous:
                new_broker = _select_broker(new_settings)

            self.settings = new_settings
            self.phase_settings = phase_settings
            self.execution.settings = new_settings
            self.execution.broker = new_broker
            self.strategy_execution.settings = new_settings
            self.strategy_execution.phase_settings = phase_settings
            self.close_reconciliation.broker = new_broker

            if persist:
                import json

                self.phase_path.parent.mkdir(parents=True, exist_ok=True)
                self.phase_path.write_text(
                    json.dumps(phase_settings.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            if old_broker is not None and old_broker is not new_broker:
                shutdown = getattr(old_broker, "shutdown", None)
                if callable(shutdown):
                    try:
                        shutdown()
                    except Exception as exc:
                        from fxars.core.logging_setup import get_logger
                        get_logger("platform").warning("broker shutdown failed: %s", exc)

            return {
                "previous_phase": previous.value,
                "runtime_phase": target.value,
                "requested_mode": normalized,
                "execution_enabled": new_settings.execution_enabled,
                "broker": getattr(new_broker, "name", None) if new_broker is not None else None,
            }

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
                     actor: str = "system", tenant_id: str = "default") -> AnalysisResult:
        return self.analysis.run(instrument_id, timeframe, as_of=as_of, actor=actor, tenant_id=tenant_id)

    def evaluate_scenario(self, scenario_id: str, *, now: datetime | None = None) -> ScenarioEvaluation:
        return self.scenario_service.evaluate(scenario_id, now=now or self.clock())

    def transition_scenario(self, scenario_id: str, status: ScenarioStatus, *, actor: str, reason: str) -> ScenarioEvaluation:
        return self.scenario_service.transition(scenario_id, status, actor=actor, reason=reason, now=self.clock())

    # ------------------------------------------------------------------ معاملات
    def apply_trading_settings(self, values: dict[str, Any], *, actor: str = "system",
                               confirm_warnings: bool = False) -> dict[str, Any]:
        """اعتبارسنجی، ذخیره و اعمال فوری تنظیمات معاملات فاز خودکار.

        مقادیر معتبر اما خارج از سقف سیاست با هشدار برمی‌گردند و تا
        ``confirm_warnings=True`` روی دیسک نوشته نمی‌شوند.
        """
        from dataclasses import replace as _replace

        from fxars.config.settings import PhaseSettings
        from fxars.config.trading_defaults import (
            apply_automated_updates,
            validate_automated_settings_soft,
        )

        instruments = self.instruments.list()
        with self._phase_lock:
            current = PhaseSettings.load(self.phase_path)
            automated = apply_automated_updates(current.automated_limited, values)
            errors, warnings = validate_automated_settings_soft(
                automated, self.settings.risk, instruments,
            )
            if errors:
                raise ValueError("؛ ".join(errors))
            if warnings and not confirm_warnings:
                return {
                    "saved": False,
                    "requires_confirmation": True,
                    "warnings": warnings,
                    "automated_limited": current.to_dict()["automated_limited"],
                }
            updated = _replace(current, automated_limited=automated)
            import json

            self.phase_path.parent.mkdir(parents=True, exist_ok=True)
            self.phase_path.write_text(
                json.dumps(updated.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        outcome = self.apply_phase(current.mode, automated_enabled=automated.enabled, persist=False)
        return {
            "saved": True,
            "requires_confirmation": False,
            "warnings": warnings,
            "automated_limited": updated.to_dict()["automated_limited"],
            "mode": outcome["requested_mode"],
            "runtime_phase": outcome["runtime_phase"],
            "broker": outcome["broker"],
        }

    def _scenario_trigger_required(self) -> bool:
        """در AUTOMATED_LIMITED، تنظیم صریح phase.json ملاک است (فقط دمو)."""
        if self.settings.phase is Phase.AUTOMATED_LIMITED:
            return bool(self.phase_settings.automated_limited.require_triggered_scenario)
        return self.settings.phase in {Phase.PAPER, Phase.DEMO, Phase.ASSISTED}

    def evaluate_risk(self, scenario_id: str, account: Any, *, rates: dict[str, Any] | None = None,
                      now: datetime | None = None, actor: str = "system",
                      tenant_id: str | None = None):
        risk_fraction = None
        max_volume = None
        if self.settings.phase is Phase.AUTOMATED_LIMITED:
            risk_fraction = self.phase_settings.automated_limited.risk_per_trade
            max_volume = self.phase_settings.automated_limited.max_volume_per_order
        return self.risk.evaluate(scenario_id, account, rates=rates, now=now or self.clock(),
                                  actor=actor, tenant_id=tenant_id, risk_fraction=risk_fraction,
                                  max_volume=max_volume)

    def run_backtest(self, instrument_id: str, timeframe: str, *, overrides: dict[str, Any] | None = None,
                     segment: BacktestSegment = BacktestSegment.ALL, as_of: datetime | None = None,
                     actor: str = "system"):
        return self.research.run(instrument_id, timeframe, config_overrides=overrides or {},
                                 segment=segment, as_of=as_of, actor=actor)

    # ------------------------------------------------------------------ بسته‌شدن معاملات
    def reconcile_closed_trades(self, *, tenant_id: str = "default", actor: str = "system"):
        return self.close_reconciliation.reconcile_all(tenant_id=tenant_id, actor=actor)

    # ------------------------------------------------------------------ سیستم
    def audit_verify(self) -> dict[str, Any]:
        return self.audit.verify()

    def kill_switch_status(self) -> dict[str, Any]:
        return self.killswitch.status()

    def kill_switch_scopes(self) -> list[dict[str, Any]]:
        return self.killswitch.all_status()

    def set_kill_switch(self, active: bool, *, actor: str, reason: str,
                        scope: str = "SYSTEM", target: str = "") -> dict[str, Any]:
        if active:
            return self.killswitch.activate(actor=actor, reason=reason, scope=scope, target=target)
        return self.killswitch.deactivate(actor=actor, reason=reason, scope=scope, target=target)

    def risk_lock_status(self) -> dict[str, Any]:
        return self.risk_lock.status()

    def set_risk_lock_review(self, *, actor: str, reason: str, release: bool = False) -> dict[str, Any]:
        return self.risk_lock.manual_review(actor=actor, reason=reason, release=release)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Platform:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

# FIX-10-PRINT-TO-LOGGER
