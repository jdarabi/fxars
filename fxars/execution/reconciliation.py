"""Reconciliation for orders in UNKNOWN state."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from fxars.audit.audit import AuditLog
from fxars.audit.outbox import EventType, Outbox
from fxars.domain.enums import OrderStatus
from fxars.domain.models import OrderIntent
from fxars.execution.state_machine import transition
from fxars.storage.repositories import OrderRepository


@dataclass
class ReconciliationResult:
    intent_id: str
    from_status: OrderStatus
    to_status: OrderStatus
    reason: str


class ReconciliationService:
    def __init__(
        self,
        *,
        orders: OrderRepository,
        broker: Any,
        audit: AuditLog,
        outbox: Outbox,
        clock: Callable[[], datetime],
    ) -> None:
        self.orders = orders
        self.broker = broker
        self.audit = audit
        self.outbox = outbox
        self.clock = clock

    def reconcile_all(self, *, actor: str = "system") -> list[ReconciliationResult]:
        unknown = self.orders.list_intents_by_status(OrderStatus.UNKNOWN)
        results: list[ReconciliationResult] = []
        for intent in unknown:
            result = self.reconcile_one(intent, actor=actor)
            if result is not None:
                results.append(result)
        return results

    def reconcile_one(
        self,
        intent: OrderIntent,
        *,
        actor: str = "system",
    ) -> ReconciliationResult | None:
        broker_order = self.broker.query(intent.client_order_id)
        now = self.clock()

        if broker_order is None:
            updated = transition(intent, OrderStatus.RECONCILIATION_REQUIRED)
            self.orders.save_intent(updated)
            self.audit.append(
                "RECONCILIATION_REQUIRED", "order_intent", intent.intent_id, actor=actor,
                payload={"reason": "broker_has_no_record"},
            )
            self.outbox.emit(
                EventType.ORDER_INTENT_CREATED,
                {"intent_id": intent.intent_id, "status": "RECONCILIATION_REQUIRED"},
                occurred_at=now,
            )
            return ReconciliationResult(
                intent_id=intent.intent_id,
                from_status=OrderStatus.UNKNOWN,
                to_status=OrderStatus.RECONCILIATION_REQUIRED,
                reason="broker_has_no_record",
            )

        target = broker_order.status
        updated = transition(intent, OrderStatus.RECONCILIATION_REQUIRED)
        if target == OrderStatus.FILLED:
            updated = transition(updated, OrderStatus.FILLED)
        elif target == OrderStatus.PARTIALLY_FILLED:
            updated = transition(updated, OrderStatus.PARTIALLY_FILLED)
        elif target == OrderStatus.REJECTED:
            updated = transition(updated, OrderStatus.REJECTED)
        elif target == OrderStatus.CANCELED:
            updated = transition(updated, OrderStatus.CANCELED)

        self.orders.save_intent(updated)
        self.audit.append(
            "RECONCILIATION_COMPLETED", "order_intent", intent.intent_id, actor=actor,
            payload={"broker_status": target.value, "final_status": updated.status.value},
        )
        return ReconciliationResult(
            intent_id=intent.intent_id,
            from_status=OrderStatus.UNKNOWN,
            to_status=updated.status,
            reason=f"broker_status={target.value}",
        )