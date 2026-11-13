"""تأیید چهارچشمی سفارش در فاز ASSISTED (بخش ۱۱-۲ سند جامع).

قاعده: سفارش باید ابتدا توسط یک اپراتور درخواست و سپس توسط اپراتور دیگری
تأیید شود. تأییدکننده نباید همان درخواست‌دهنده باشد و تأیید پس از TTL منقضی
می‌شود. این سرویس فقط وضعیت تأیید را مدیریت می‌کند؛ ارسال سفارش همچنان از
مسیر ExecutionService و RiskGate می‌گذرد.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from fxars.audit.audit import AuditLog
from fxars.core.errors import (
    AuthorizationError,
    NotFoundError,
    PhaseViolationError,
    ValidationError,
)
from fxars.core.timeutil import ensure_utc
from fxars.domain.enums import ApprovalStatus, Phase
from fxars.domain.models import OrderApproval
from fxars.storage.repositories import ApprovalRepository, OrderRepository

DEFAULT_APPROVAL_TTL_SECONDS = 15 * 60


class ApprovalService:
    def __init__(
        self,
        *,
        approvals: ApprovalRepository,
        orders: OrderRepository,
        clock: Callable[[], datetime],
        audit: AuditLog,
        ttl_seconds: int = DEFAULT_APPROVAL_TTL_SECONDS,
    ) -> None:
        self.approvals = approvals
        self.orders = orders
        self.clock = clock
        self.audit = audit
        self.ttl_seconds = ttl_seconds

    # ------------------------------------------------------------------
    def request(self, intent_id: str, *, actor: str) -> OrderApproval:
        intent = self.orders.get_intent(intent_id)
        if intent is None:
            raise NotFoundError(f"OrderIntent {intent_id} یافت نشد.")
        if intent.phase is not Phase.ASSISTED:
            raise ValidationError(
                "درخواست تأیید فقط در فاز ASSISTED معنا دارد.",
                details={"phase": intent.phase.value},
            )
        now = ensure_utc(self.clock())
        existing = self.approvals.get(intent_id)
        if existing is not None and existing.status is ApprovalStatus.PENDING:
            if not existing.is_expired(now):
                return existing
            existing = OrderApproval(
                intent_id=existing.intent_id,
                requested_by=existing.requested_by,
                requested_at=existing.requested_at,
                expires_at=existing.expires_at,
                status=ApprovalStatus.EXPIRED,
                approved_by=existing.approved_by,
                decided_at=existing.decided_at,
                reason=existing.reason,
            )
            self.approvals.save(existing)

        approval = OrderApproval(
            intent_id=intent_id,
            requested_by=actor,
            requested_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
            status=ApprovalStatus.PENDING,
        )
        with self.approvals.db.transaction():
            self.approvals.save(approval)
            self.audit.append(
                "ORDER_APPROVAL_REQUESTED",
                "order_intent",
                intent_id,
                actor=actor,
                payload={"expires_at": approval.expires_at.isoformat()},
            )
        return approval

    def approve(self, intent_id: str, *, approved_by: str, reason: str = "") -> OrderApproval:
        approval = self._pending(intent_id)
        if approved_by.strip().lower() == approval.requested_by.strip().lower():
            raise AuthorizationError(
                "تأییدکننده باید با درخواست‌دهنده متفاوت باشد (تأیید چهارچشمی).",
                details={"intent_id": intent_id},
            )
        now = ensure_utc(self.clock())
        approved = OrderApproval(
            intent_id=approval.intent_id,
            requested_by=approval.requested_by,
            requested_at=approval.requested_at,
            expires_at=approval.expires_at,
            status=ApprovalStatus.APPROVED,
            approved_by=approved_by,
            decided_at=now,
            reason=reason,
        )
        with self.approvals.db.transaction():
            self.approvals.save(approved)
            self.audit.append(
                "ORDER_APPROVAL_APPROVED",
                "order_intent",
                intent_id,
                actor=approved_by,
                payload={"requested_by": approval.requested_by, "reason": reason},
            )
        return approved

    def reject(self, intent_id: str, *, rejected_by: str, reason: str) -> OrderApproval:
        approval = self._pending(intent_id)
        rejected = OrderApproval(
            intent_id=approval.intent_id,
            requested_by=approval.requested_by,
            requested_at=approval.requested_at,
            expires_at=approval.expires_at,
            status=ApprovalStatus.REJECTED,
            approved_by=rejected_by,
            decided_at=ensure_utc(self.clock()),
            reason=reason,
        )
        with self.approvals.db.transaction():
            self.approvals.save(rejected)
            self.audit.append(
                "ORDER_APPROVAL_REJECTED",
                "order_intent",
                intent_id,
                actor=rejected_by,
                payload={"reason": reason},
            )
        return rejected

    def get(self, intent_id: str) -> OrderApproval | None:
        return self.approvals.get(intent_id)

    def require_approved(self, intent_id: str, *, now: datetime | None = None) -> OrderApproval:
        approval = self.approvals.get(intent_id)
        moment = ensure_utc(now or self.clock())
        if approval is None:
            raise PhaseViolationError(
                "در فاز ASSISTED ارسال سفارش بدون تأیید اپراتور مجاز نیست.",
                details={"intent_id": intent_id, "reason": "APPROVAL_MISSING"},
            )
        if approval.is_expired(moment):
            if approval.status is ApprovalStatus.APPROVED:
                expired = OrderApproval(
                    intent_id=approval.intent_id,
                    requested_by=approval.requested_by,
                    requested_at=approval.requested_at,
                    expires_at=approval.expires_at,
                    status=ApprovalStatus.EXPIRED,
                    approved_by=approval.approved_by,
                    decided_at=approval.decided_at,
                    reason=approval.reason,
                )
                self.approvals.save(expired)
            raise PhaseViolationError(
                "تأیید سفارش منقضی شده است.",
                details={"intent_id": intent_id, "reason": "APPROVAL_EXPIRED"},
            )
        if approval.status is not ApprovalStatus.APPROVED:
            raise PhaseViolationError(
                "تأیید معتبر برای این سفارش ثبت نشده است.",
                details={"intent_id": intent_id, "status": approval.status.value},
            )
        if not approval.approved_by:
            raise PhaseViolationError(
                "تأییدکننده نامشخص است.", details={"intent_id": intent_id},
            )
        return approval

    def _pending(self, intent_id: str) -> OrderApproval:
        approval = self.approvals.get(intent_id)
        if approval is None:
            raise NotFoundError(f"درخواست تأیید برای {intent_id} یافت نشد.")
        if approval.is_expired(ensure_utc(self.clock())):
            raise ValidationError(
                "درخواست تأیید منقضی شده است؛ درخواست جدید لازم است.",
                details={"intent_id": intent_id},
            )
        if approval.status is not ApprovalStatus.PENDING:
            raise ValidationError(
                "این درخواست تأیید قبلاً تصمیم‌گیری شده است.",
                details={"intent_id": intent_id, "status": approval.status.value},
            )
        return approval
