"""Kill Switch سراسری: Enforcement در سرویس ریسک/اجرا، نه فقط UI."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fxars.audit.audit import AuditAction, AuditLog
from fxars.audit.outbox import EventType, Outbox
from fxars.core.context import current_correlation_id
from fxars.core.errors import KillSwitchActiveError, ValidationError
from fxars.core.timeutil import format_ts, utcnow
from fxars.storage.repositories import SystemStateRepository

KEY = "kill_switch"


class KillSwitch:
    def __init__(self, state: SystemStateRepository, audit: AuditLog, outbox: Outbox | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.state = state
        self.audit = audit
        self.outbox = outbox
        self.clock = clock or utcnow

    def status(self) -> dict[str, Any]:
        value = self.state.get(KEY, {"active": False})
        value.setdefault("active", False)
        return value

    def is_active(self) -> bool:
        return bool(self.status().get("active"))

    def activate(self, *, actor: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValidationError("فعال‌سازی Kill Switch نیازمند دلیل ثبت‌شده است.")
        moment = self.clock()
        value = {
            "active": True,
            "reason": reason,
            "actor": actor,
            "since": format_ts(moment),
            "correlation_id": current_correlation_id(),
        }
        self.state.set(KEY, value, actor)
        self._audit_and_emit(value, actor, "activated", moment)
        return value

    def deactivate(self, *, actor: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValidationError("غیرفعال‌سازی Kill Switch نیازمند دلیل ثبت‌شده است.")
        moment = self.clock()
        value = {
            "active": False,
            "reason": reason,
            "actor": actor,
            "since": format_ts(moment),
            "previous": self.status(),
            "correlation_id": current_correlation_id(),
        }
        self.state.set(KEY, value, actor)
        self._audit_and_emit(value, actor, "deactivated", moment)
        return value

    def assert_inactive(self) -> None:
        if self.is_active():
            status = self.status()
            raise KillSwitchActiveError(
                f"Kill Switch فعال است: {status.get('reason', '')}",
                details={"since": status.get("since"), "actor": status.get("actor")},
            )

    def _audit_and_emit(self, value: dict[str, Any], actor: str, action: str, moment: datetime) -> None:
        self.audit.append(
            AuditAction.KILL_SWITCH_CHANGED,
            "system",
            KEY,
            actor=actor,
            payload={"action": action, **value},
        )
        if self.outbox is not None:
            self.outbox.emit(
                EventType.KILL_SWITCH_CHANGED,
                {"action": action, "active": value.get("active"), "reason": value.get("reason"), "actor": actor},
                occurred_at=moment,
            )
