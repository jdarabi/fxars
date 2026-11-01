"""ماشین حالت سفارش (MVP-2+) با گذارهای صریح."""

from __future__ import annotations

from dataclasses import replace

from fxars.core.errors import ConflictError
from fxars.domain.enums import OrderStatus
from fxars.domain.models import OrderIntent

ALLOWED: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.INTENT_CREATED: {OrderStatus.RISK_APPROVED, OrderStatus.REJECTED},
    OrderStatus.RISK_APPROVED: {OrderStatus.SUBMITTED, OrderStatus.EXPIRED, OrderStatus.REJECTED},
    OrderStatus.SUBMITTED: {OrderStatus.ACKNOWLEDGED, OrderStatus.REJECTED, OrderStatus.UNKNOWN},
    OrderStatus.ACKNOWLEDGED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELED,
                               OrderStatus.REJECTED, OrderStatus.EXPIRED},
    OrderStatus.PARTIALLY_FILLED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELED,
                                   OrderStatus.EXPIRED},
    OrderStatus.FILLED: {OrderStatus.CLOSED},
    OrderStatus.UNKNOWN: {OrderStatus.RECONCILIATION_REQUIRED, OrderStatus.ACKNOWLEDGED},
    OrderStatus.RECONCILIATION_REQUIRED: {OrderStatus.ACKNOWLEDGED, OrderStatus.FILLED, OrderStatus.CANCELED,
                                          OrderStatus.REJECTED},
    OrderStatus.CANCELED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.EXPIRED: set(),
    OrderStatus.CLOSED: set(),
}


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in ALLOWED.get(current, set())


def transition(intent: OrderIntent, target: OrderStatus) -> OrderIntent:
    if not can_transition(intent.status, target):
        raise ConflictError(
            f"گذار وضعیت سفارش از {intent.status.value} به {target.value} مجاز نیست.",
            details={"intent_id": intent.intent_id, "from": intent.status.value, "to": target.value},
        )
    return replace(intent, status=target)
