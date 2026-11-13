"""اجرای سفارش بر پایه سیگنال استراتژی با عبور اجباری از RiskGate.

این سرویس جای مسیر قدیمی API را می‌گیرد که OrderIntent می‌ساخت و مستقیم به
`MT5Broker` می‌فرستاد (دور زدن ریسک، Kill Switch و سقف‌های فاز). اکنون هر سیگنال
استراتژی ابتدا به Scenario تبدیل، سپس با RiskService ارزیابی و در نهایت از
ExecutionService ارسال می‌شود.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from fxars.audit.audit import AuditLog
from fxars.config.settings import PhaseSettings, Settings
from fxars.core.ids import stable_id
from fxars.core.numerics import ZERO, to_decimal
from fxars.core.timeutil import ensure_utc
from fxars.domain.enums import Direction, Phase, ScenarioStatus, Timeframe
from fxars.domain.models import (
    AccountSnapshot,
    Candle,
    OrderApproval,
    OrderIntent,
    RiskDecision,
    Scenario,
)
from fxars.execution.approval import ApprovalService
from fxars.execution.service import ExecutionService
from fxars.risk.limits import ExecutionLimitInput, execution_block_reason
from fxars.risk.service import RiskService
from fxars.storage.repositories import InstrumentRepository, OrderRepository, ScenarioRepository

SCENARIO_EXPIRY_BARS = 8


@dataclass(frozen=True)
class StrategyTradeOutcome:
    status: str
    reason: str
    scenario: Scenario | None = None
    decision: RiskDecision | None = None
    intent: OrderIntent | None = None
    approval: OrderApproval | None = None
    broker_order: Any | None = None
    fills: tuple[Any, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "scenario_id": self.scenario.scenario_id if self.scenario else None,
            "risk_decision": (
                {
                    "decision_id": self.decision.decision_id,
                    "approved": self.decision.approved,
                    "reason_code": self.decision.reason_code.value,
                    "reason_detail": self.decision.reason_detail,
                    "position_size": str(self.decision.position_size),
                    "checks_failed": list(self.decision.checks_failed),
                }
                if self.decision
                else None
            ),
            "intent": self.intent.to_dict() if self.intent else None,
            "approval": self.approval.to_dict() if self.approval else None,
            "broker_order": (
                self.broker_order.to_dict() if hasattr(self.broker_order, "to_dict") else None
            ),
            "fills": [
                fill.to_dict() if hasattr(fill, "to_dict") else str(fill)
                for fill in self.fills
            ],
        }


class StrategyExecutionService:
    def __init__(
        self,
        *,
        settings: Settings,
        phase_settings: PhaseSettings,
        clock: Callable[[], datetime],
        instruments: InstrumentRepository,
        scenarios: ScenarioRepository,
        orders: OrderRepository,
        risk: RiskService,
        execution: ExecutionService,
        approvals: ApprovalService,
        audit: AuditLog,
        broker_is_real: Callable[[], bool] | None = None,
        quota=None,
    ) -> None:
        self.settings = settings
        self.phase_settings = phase_settings
        self.clock = clock
        self.instruments = instruments
        self.scenarios = scenarios
        self.orders = orders
        self.risk = risk
        self.execution = execution
        self.approvals = approvals
        self.audit = audit
        self._broker_is_real = broker_is_real
        self.quota = quota

    # ------------------------------------------------------------------
    def execute(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        analysis: dict[str, Any],
        candle: Candle,
        account: AccountSnapshot,
        price: Decimal,
        pip_size: Decimal,
        spread_pips: Decimal | None = None,
        rates: dict[str, Any] | None = None,
        actor: str = "system",
        tenant_id: str = "default",
    ) -> StrategyTradeOutcome:
        phase = self.settings.phase
        if phase.is_advisor_mode:
            raise_phase = f"PHASE_{phase.value}"
            self.audit.append(
                "ORDER_INTENT_BLOCKED", "instrument", instrument_id, actor=actor,
                payload={"reason": raise_phase, "source": "strategy"},
            )
            self._phase_error(phase)
        if not self.settings.execution_enabled:
            self._phase_error(phase)

        signal = str(analysis.get("signal", "NO_TRADE")).upper()
        if signal not in ("LONG", "SHORT"):
            return StrategyTradeOutcome(status="NO_TRADE", reason="سیگنال معتبری نیست.")

        instrument = self.instruments.find(instrument_id)
        if instrument is None:
            return StrategyTradeOutcome(status="BLOCKED", reason=f"نماد {instrument_id} ثبت نشده است.")
        entry = to_decimal(analysis.get("entry"), field="entry")
        stop = to_decimal(analysis.get("stop"), field="stop")
        target_raw = analysis.get("target")
        target = to_decimal(target_raw, field="target") if target_raw is not None else None
        if entry <= ZERO or stop <= ZERO:
            return StrategyTradeOutcome(status="BLOCKED", reason="entry/stop نامعتبر است.")

        now = ensure_utc(self.clock())
        tf = Timeframe.parse(timeframe)
        best = analysis.get("best") or {}
        try:
            strength = float(best.get("score", analysis.get("score", 0.0)) or 0.0)
        except (TypeError, ValueError):
            strength = 0.0
        if self.quota is not None:
            self.quota.check_live_scenario(tenant_id)
        scenario_id = stable_id(
            "sc", f"strategy:{instrument_id}:{tf.value}:{now.isoformat()}",
            "" if tenant_id == "default" else tenant_id, length=20,
        )
        scenario = Scenario(
            scenario_id=scenario_id,
            instrument_id=instrument_id,
            timeframe=tf.value,
            direction=Direction.LONG if signal == "LONG" else Direction.SHORT,
            status=ScenarioStatus.TRIGGERED,
            entry_condition={"kind": "strategy_entry", "level": format(entry, "f")},
            invalidation_condition={"kind": "strategy_stop", "level": format(stop, "f")},
            stop_logic={"kind": "strategy_stop", "level": format(stop, "f")},
            target_logic=(
                ({"kind": "strategy_target", "price": format(target, "f")},)
                if target is not None
                else ()
            ),
            expiry_at=now + tf.delta * SCENARIO_EXPIRY_BARS,
            evidence_ids=(),
            analysis_run_id=f"strategy:{best.get('name', 'selector')}",
            decision_explanation=str(analysis.get("reason", "")),
            created_at=now,
            updated_at=now,
            rules_version=self.settings.rules_version,
            config_hash=self.settings.config_hash(),
            strength=max(0.0, strength),
            tenant_id=tenant_id,
        )
        with self.scenarios.db.transaction():
            self.scenarios.save(scenario)

        # اسپرد واقعی تیک را جایگزین اسپرد (احتمالاً صفر) کندل می‌کنیم تا Gate
        # بر پایه همان اسپردی تصمیم بگیرد که سفارش با آن ارسال می‌شود.
        market_candle = candle
        measured_spread = spread_pips if spread_pips is not None else self._spread_pips(analysis)
        if measured_spread is not None and pip_size > ZERO:
            market_candle = replace(candle, spread=measured_spread * pip_size)

        risk_fraction = None
        if phase is Phase.AUTOMATED_LIMITED:
            risk_fraction = self.phase_settings.automated_limited.risk_per_trade
        decision = self.risk.evaluate(
            scenario_id, account, rates=rates or {}, now=now, actor=actor, candle=market_candle,
            tenant_id=tenant_id, risk_fraction=risk_fraction,
        )
        if not decision.approved:
            return StrategyTradeOutcome(
                status="RISK_REJECTED",
                reason=decision.reason_detail,
                scenario=scenario,
                decision=decision,
            )

        automated = self.phase_settings.automated_limited
        max_spread = self.settings.risk.max_spread_pips
        if phase is Phase.AUTOMATED_LIMITED:
            max_spread = min(max_spread, automated.max_spread_pips)
        block_reason = execution_block_reason(
            ExecutionLimitInput(
                phase=phase,
                execute_orders=True,
                execution_enabled=self.settings.execution_enabled,
                killswitch_active=self.execution.killswitch.is_active(),
                broker_is_real=self._is_real_broker(),
                position_size=decision.position_size,
                automated=automated,
                instrument=instrument_id,
                timeframe=tf.value,
                scenario_status=scenario.status,
                spread_pips=measured_spread,
                max_spread_pips=max_spread,
                open_positions=account.open_positions,
                trades_today=self._trades_today(now),
                paper_broker=self._broker_name() == "paper",
            )
        )
        if block_reason is not None:
            self.audit.append(
                "ORDER_BLOCKED", "scenario", scenario_id, actor=actor,
                payload={"reason": block_reason, "instrument": instrument_id, "timeframe": tf.value},
            )
            return StrategyTradeOutcome(
                status="BLOCKED", reason=block_reason, scenario=scenario, decision=decision,
            )

        intent = self.execution.create_intent(scenario_id, actor=actor, tenant_id=tenant_id)
        if phase is Phase.ASSISTED:
            approval = self.approvals.request(intent.intent_id, actor=actor)
            return StrategyTradeOutcome(
                status="AWAITING_APPROVAL",
                reason="سفارش در انتظار تأیید اپراتور دوم است.",
                scenario=scenario, decision=decision, intent=intent, approval=approval,
            )

        submitted = self.execution.submit(
            intent.intent_id, price=price, pip_size=pip_size, actor=actor,
        )
        return StrategyTradeOutcome(
            status="SUBMITTED",
            reason="سفارش از مسیر RiskGate ارسال شد.",
            scenario=scenario,
            decision=decision,
            intent=submitted,
        )

    # ------------------------------------------------------------------
    def submit_approved(self, intent_id: str, *, price: Decimal, pip_size: Decimal, actor: str) -> OrderIntent:
        """ارسال سفارش ASSISTED پس از تأیید؛ همچنان TTL تصمیم ریسک بررسی می‌شود."""
        if self.settings.phase is not Phase.ASSISTED:
            self._phase_error(self.settings.phase, "این عملیات فقط در فاز ASSISTED مجاز است.")
        return self.execution.submit(intent_id, price=price, pip_size=pip_size, actor=actor)

    # ------------------------------------------------------------------
    def _spread_pips(self, analysis: dict[str, Any]) -> Decimal | None:
        raw = analysis.get("spread_pips")
        if raw is None:
            return None
        try:
            return max(ZERO, to_decimal(raw))
        except (TypeError, ValueError):
            return None

    def _trades_today(self, now: datetime) -> int:
        calendar = getattr(self.risk, "calendar", None)
        day_start = (
            calendar.trading_day_start(now)
            if calendar is not None and hasattr(calendar, "trading_day_start")
            else now.replace(hour=0, minute=0, second=0, microsecond=0)
        )
        return self.orders.count_intents_since(day_start)

    def _is_real_broker(self) -> bool:
        if self._broker_is_real is not None:
            return bool(self._broker_is_real())
        return self._broker_name() == "mt5"

    def _broker_name(self) -> str:
        broker = getattr(self.execution, "broker", None)
        return str(getattr(broker, "name", "") or "")

    @staticmethod
    def _phase_error(phase: Phase, message: str | None = None) -> None:
        from fxars.core.errors import PhaseViolationError

        raise PhaseViolationError(
            message or "ارسال سفارش در فاز فعلی مجاز نیست.",
            details={"phase": phase.value},
        )
