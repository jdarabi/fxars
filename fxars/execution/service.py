"""سرویس اجرا (MVP-2+): در MVP-1 هیچ مسیر ارسال سفارش فعال نیست.

Phase Guard و Risk Gate هر دو در سطح سرویس enforce می‌شوند؛ API یا job جانبی
نمی‌تواند این لایه را دور بزند (AC-05).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from fxars.audit.audit import AuditAction, AuditLog
from fxars.audit.outbox import EventType, Outbox
from fxars.config.settings import Settings
from fxars.core.errors import NotFoundError, PhaseViolationError, RiskRejectedError, ValidationError
from fxars.core.ids import new_id, stable_id
from fxars.domain.enums import OrderStatus, Phase, Side
from fxars.domain.models import OrderIntent, RiskDecision
from fxars.execution.state_machine import transition
from fxars.risk.killswitch import KillSwitch
from fxars.storage.repositories import OrderRepository, RiskRepository, ScenarioRepository


def _scenario_status_check_required(settings) -> bool:
    """FIX-DUAL: در فازهای خودکار، سناریو باید TRIGGERED باشد."""
    from fxars.domain.enums import Phase
    return settings.phase in {
        Phase.PAPER, Phase.DEMO, Phase.ASSISTED, Phase.AUTOMATED_LIMITED,
    }


class ExecutionService:
    def __init__(
        self,
        *,
        settings: Settings,
        clock: Callable[[], datetime],
        scenarios: ScenarioRepository,
        decisions: RiskRepository,
        orders: OrderRepository,
        killswitch: KillSwitch,
        audit: AuditLog,
        outbox: Outbox,
        broker: Any = None,
        approvals: Any = None,
        scenario_gate: Callable[[], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.scenarios = scenarios
        self.decisions = decisions
        self.orders = orders
        self.killswitch = killswitch
        self.audit = audit
        self.outbox = outbox
        self.broker = broker
        self.approvals = approvals
        self.scenario_gate = scenario_gate

    @property
    def phase(self) -> Phase:
        return self.settings.phase

    # ------------------------------------------------------------------
    def create_intent(
        self,
        scenario_id: str,
        *,
        client_order_id: str | None = None,
        actor: str = "system",
        tenant_id: str | None = None,
    ) -> OrderIntent:
        if not self.settings.execution_enabled:
            self.audit.append(
                AuditAction.ORDER_INTENT_BLOCKED, "scenario", scenario_id, actor=actor,
                payload={"reason": "PHASE_READ_ONLY", "phase": self.phase.value},
            )
            raise PhaseViolationError(
                "در فاز Read-only (MVP-1) ساخت OrderIntent و ارسال سفارش مجاز نیست.",
                details={"phase": self.phase.value},
            )
        self.killswitch.assert_inactive()

        # FIX-DUAL: فقط سناریوی TRIGGERED مجاز به ساخت OrderIntent است
        requires_triggered = (
            bool(self.scenario_gate())
            if self.scenario_gate is not None
            else _scenario_status_check_required(self.settings)
        )
        if requires_triggered:
            from fxars.domain.enums import Phase as _P
            from fxars.domain.enums import ScenarioStatus as _SS
            scenario_pre = self.scenarios.get(scenario_id)
            # FIX-DUAL: PAPER auto-trigger
            if (
                self.settings.phase is _P.PAPER
                and scenario_pre.status in (_SS.WATCH, _SS.ARMED)
            ):
                now_pre = self.clock()
                promoted = scenario_pre.with_status(_SS.TRIGGERED, when=now_pre)
                self.scenarios.save(promoted)
                self.audit.append(
                    "SCENARIO_TRANSITION", "scenario", scenario_id, actor=actor,
                    payload={
                        "from": scenario_pre.status.value,
                        "to": _SS.TRIGGERED.value,
                        "event": "paper_auto_trigger",
                    },
                )
                scenario_pre = promoted
            if scenario_pre.status is not _SS.TRIGGERED:
                self.audit.append(
                    "ORDER_INTENT_BLOCKED", "scenario", scenario_id, actor=actor,
                    payload={
                        "reason": "SCENARIO_NOT_TRIGGERED",
                        "status": scenario_pre.status.value,
                    },
                )
                raise PhaseViolationError(
                    "ساخت OrderIntent فقط برای سناریوی TRIGGERED مجاز است.",
                    details={"status": scenario_pre.status.value},
                )

        scenario = self.scenarios.get(scenario_id)
        if tenant_id is not None and scenario.tenant_id != tenant_id:
            raise NotFoundError(f"سناریو {scenario_id} یافت نشد.", details={"scenario_id": scenario_id})
        if scenario.risk_decision_id is None:
            raise RiskRejectedError("سناریو RiskDecision تأییدشده ندارد.")
        decision: RiskDecision = self.decisions.get(scenario.risk_decision_id)
        now = self.clock()
        if not decision.approved or decision.valid_until <= now:
            raise RiskRejectedError(
                "RiskDecision منقضی یا رد شده است.",
                details={
                    "decision_id": decision.decision_id,
                    "reason": decision.reason_code.value,
                },
            )

        identifier = client_order_id or (
            f"fxars-{scenario.instrument_id.lower()}-"
            f"{now.strftime('%Y%m%d%H%M%S')}-{new_id('', 4)}"
        )
        existing = self.orders.find_by_client_id(identifier)
        if existing is not None:
            return existing

        side = Side.BUY if scenario.direction.value == "LONG" else Side.SELL
        targets = scenario.target_logic
        take_profit = (
            Decimal(targets[0]["price"])
            if targets and targets[0].get("price")
            else None
        )
        intent = OrderIntent(
            intent_id=stable_id("oi", identifier, length=20),
            client_order_id=identifier,
            risk_decision_id=decision.decision_id,
            instrument_id=scenario.instrument_id,
            side=side,
            order_type="MARKET",
            volume=decision.position_size,
            stop_loss=decision.stop_loss,
            take_profit=take_profit,
            created_at=now,
            status=OrderStatus.INTENT_CREATED,
            phase=self.phase,
            tenant_id=scenario.tenant_id,
        )
        intent = transition(intent, OrderStatus.RISK_APPROVED)
        with self.orders.db.transaction():
            self.orders.save_intent(intent)
            self.scenarios.save(scenario)
            self.audit.append(
                "ORDER_INTENT_CREATED", "order_intent", intent.intent_id, actor=actor,
                payload={"client_order_id": identifier, "scenario_id": scenario_id},
            )
            self.outbox.emit(
                EventType.ORDER_INTENT_CREATED,
                {
                    "intent_id": intent.intent_id,
                    "client_order_id": identifier,
                    "volume": str(intent.volume),
                    "side": side.value,
                },
                occurred_at=now,
            )
        return intent

    # ------------------------------------------------------------------
    def submit(
        self,
        intent_id: str,
        *,
        price: Decimal,
        pip_size: Decimal,
        actor: str = "system",
    ) -> OrderIntent:
        # FIX-DUAL: در ADVISOR هیچ ارسالی مجاز نیست
        if self.phase.is_advisor_mode:
            raise PhaseViolationError(
                "ارسال سفارش در فاز مشاور (ADVISOR/READ_ONLY) مجاز نیست.",
                details={"phase": self.phase.value},
            )
        if self.phase is Phase.READ_ONLY:
            raise PhaseViolationError("ارسال سفارش در فاز Read-only ممنوع است.")
        self.killswitch.assert_inactive()

        # FIX-DUAL: در submit وضعیت سناریو از intent خوانده میشود

        intent = self.orders.get_intent(intent_id)
        if intent is None:
            raise ValidationError("OrderIntent یافت نشد.")

        # پاسخ‌گویی چهارچشمی: در ASSISTED هیچ ارسالی بدون تأیید اپراتور دیگر مجاز نیست.
        if self.phase is Phase.ASSISTED:
            if self.approvals is None:
                raise PhaseViolationError(
                    "سرویس تأیید در فاز ASSISTED پیکربندی نشده است؛ ارسال مسدود شد.",
                    details={"phase": self.phase.value},
                )
            self.approvals.require_approved(intent_id, now=self.clock())

        # FIX-P0-4: re-check decision TTL at submission time
        decision = self.decisions.get(intent.risk_decision_id)
        now = self.clock()
        if not decision.approved or decision.valid_until <= now:
            raise RiskRejectedError(
                "RiskDecision expired or rejected at submission time.",
                details={
                    "decision_id": decision.decision_id,
                    "reason": decision.reason_code.value,
                    "valid_until": decision.valid_until.isoformat(),
                },
            )

        if self.broker is None:
            raise ValidationError("آداپتر بروکر پیکربندی نشده است.")

        intent = transition(intent, OrderStatus.SUBMITTED)
        broker_order, fills = self.broker.submit(
            intent, price=price, pip_size=pip_size,
        )

        # FIX-P6-5: honor broker's actual status
        # (FILLED, PARTIALLY_FILLED, UNKNOWN, REJECTED, CANCELED, EXPIRED)
        target = broker_order.status
        intent = transition(intent, OrderStatus.ACKNOWLEDGED)
        intent = transition(intent, target)

        with self.orders.db.transaction():
            self.orders.save_intent(intent)
            self.orders.save_broker_order(broker_order)
            for fill in fills:
                self.orders.save_fill(fill)
            self.audit.append(
                "ORDER_SUBMITTED", "order_intent", intent.intent_id, actor=actor,
                payload={
                    "broker_order_id": broker_order.broker_order_id,
                    "status": target.value,
                    "fills": len(fills),
                },
            )
        return intent
