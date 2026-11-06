"""ماشین حالت سفارش (MVP-2+) با گذارهای صریح."""

from __future__ import annotations

from dataclasses import replace

from fxars.core.errors import ConflictError
from fxars.domain.enums import OrderStatus
from fxars.domain.models import OrderIntent

# ترتیب گذارهای مجاز:
#   INTENT_CREATED -> RISK_APPROVED (پس از تأیید ریسک)
#   RISK_APPROVED  -> SUBMITTED     (پس از enforce مجدد Kill Switch/TTL)
#   SUBMITTED      -> ACKNOWLEDGED  (پس از پذیرش بروکر)
#   ACKNOWLEDGED   -> FILLED/PARTIAL/CANCELED/REJECTED/EXPIRED/UNKNOWN
#   FILLED         -> CLOSED        (پس از بسته شدن معامله)
#   UNKNOWN        -> RECONCILIATION_REQUIRED (پس از تطبیق)
#   RECONCILIATION_REQUIRED -> ACKNOWLEDGED/FILLED/CANCELED/REJECTED/EXPIRED
ALLOWED: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.INTENT_CREATED: {
        OrderStatus.RISK_APPROVED,
        OrderStatus.REJECTED,
    },
    OrderStatus.RISK_APPROVED: {
        OrderStatus.SUBMITTED,
        OrderStatus.EXPIRED,
        OrderStatus.REJECTED,
    },
    OrderStatus.SUBMITTED: {
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.REJECTED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.ACKNOWLEDGED: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        # FIX-P6-5: broker may report timeout AFTER accepting the order.
        OrderStatus.UNKNOWN,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.EXPIRED,
        # FIX-P6-5: partial fill + later connection loss -> UNKNOWN
        OrderStatus.UNKNOWN,
    },
    OrderStatus.FILLED: {
        OrderStatus.CLOSED,
    },
    OrderStatus.UNKNOWN: {
        OrderStatus.RECONCILIATION_REQUIRED,
        OrderStatus.ACKNOWLEDGED,
        # FIX-P6-5: reconciliation may resolve UNKNOWN to a terminal state
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.RECONCILIATION_REQUIRED: {
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.FILLED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    },
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
            details={
                "intent_id": intent.intent_id,
                "from": intent.status.value,
                "to": target.value,
                "allowed": sorted(s.value for s in ALLOWED.get(intent.status, set())),
            },
        )
    return replace(intent, status=target)


def allowed_targets(current: OrderStatus) -> list[str]:
    """Return the list of statuses the current status can transition to."""
    return sorted(s.value for s in ALLOWED.get(current, set()))


def is_terminal(status: OrderStatus) -> bool:
    """A status is terminal if it has no outgoing transitions."""
    return not ALLOWED.get(status, set())
