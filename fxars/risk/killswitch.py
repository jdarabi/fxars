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
SCOPE_SYSTEM = "SYSTEM"
SCOPE_MODULE = "MODULE"
SCOPE_ACCOUNT = "ACCOUNT"


class KillSwitch:
    """Kill Switch با سه سطح سامانه، ماژول و حساب (بخش ۸-۳ سند تکمیلی ۱.۱).

    کلید سطح سامانه همان ``kill_switch`` قبلی است تا سازگاری حفظ شود. کلیدهای
    سطح ماژول/حساب با ``kill_switch:MODULE:<name>`` و ``kill_switch:ACCOUNT:<id>``
    ذخیره می‌شوند. ``is_active()`` بدون آرگومان اگر هر سطحی فعال باشد True است
    (Fail-Safe)؛ برای بررسی دقیق، scope و target را بدهید.
    """

    def __init__(self, state: SystemStateRepository, audit: AuditLog, outbox: Outbox | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.state = state
        self.audit = audit
        self.outbox = outbox
        self.clock = clock or utcnow

    @staticmethod
    def _key(scope: str, target: str = "") -> str:
        scope = (scope or SCOPE_SYSTEM).upper()
        if scope == SCOPE_SYSTEM:
            return KEY
        if not target.strip():
            raise ValidationError(f"Kill Switch سطح {scope} نیازمند target است.")
        return f"{KEY}:{scope}:{target.strip()}"

    def status(self, scope: str = SCOPE_SYSTEM, target: str = "") -> dict[str, Any]:
        value = self.state.get(self._key(scope, target), {"active": False})
        value.setdefault("active", False)
        value.setdefault("scope", (scope or SCOPE_SYSTEM).upper())
        value.setdefault("target", target)
        return value

    def all_status(self) -> list[dict[str, Any]]:
        rows = self.state.db.query(
            "SELECT key FROM system_state WHERE key = ? OR key LIKE ? ORDER BY key",
            (KEY, f"{KEY}:%"),
        )
        values: list[dict[str, Any]] = []
        for row in rows:
            value = self.state.get(row["key"], {})
            value.setdefault("active", False)
            value["key"] = row["key"]
            values.append(value)
        if not values:
            values.append(self.status())
        return values

    def is_active(self, scope: str | None = None, target: str = "") -> bool:
        if scope is None:
            if bool(self.status().get("active")):
                return True
            return any(item.get("active") for item in self.all_status() if item.get("key") != KEY)
        return bool(self.status(scope, target).get("active")) or bool(self.status().get("active"))

    def activate(self, *, actor: str, reason: str, scope: str = SCOPE_SYSTEM,
                 target: str = "") -> dict[str, Any]:
        if not reason.strip():
            raise ValidationError("فعال‌سازی Kill Switch نیازمند دلیل ثبت‌شده است.")
        scope = (scope or SCOPE_SYSTEM).upper()
        if scope not in {SCOPE_SYSTEM, SCOPE_MODULE, SCOPE_ACCOUNT}:
            raise ValidationError(f"سطح Kill Switch نامعتبر است: {scope}")
        moment = self.clock()
        value = {
            "active": True,
            "scope": scope,
            "target": target,
            "reason": reason,
            "actor": actor,
            "since": format_ts(moment),
            "correlation_id": current_correlation_id(),
        }
        self.state.set(self._key(scope, target), value, actor)
        self._audit_and_emit(value, actor, "activated", moment)
        return value

    def deactivate(self, *, actor: str, reason: str, scope: str = SCOPE_SYSTEM,
                   target: str = "") -> dict[str, Any]:
        if not reason.strip():
            raise ValidationError("غیرفعال‌سازی Kill Switch نیازمند دلیل ثبت‌شده است.")
        scope = (scope or SCOPE_SYSTEM).upper()
        moment = self.clock()
        value = {
            "active": False,
            "scope": scope,
            "target": target,
            "reason": reason,
            "actor": actor,
            "since": format_ts(moment),
            "previous": self.status(scope, target),
            "correlation_id": current_correlation_id(),
        }
        self.state.set(self._key(scope, target), value, actor)
        self._audit_and_emit(value, actor, "deactivated", moment)
        return value

    def assert_inactive(self, scope: str | None = None, target: str = "") -> None:
        if self.is_active(scope, target):
            status = self.status(scope or SCOPE_SYSTEM, target)
            raise KillSwitchActiveError(
                f"Kill Switch فعال است: {status.get('reason', '')}",
                details={"scope": status.get("scope"), "target": status.get("target"),
                         "since": status.get("since"), "actor": status.get("actor")},
            )

    def _audit_and_emit(self, value: dict[str, Any], actor: str, action: str, moment: datetime) -> None:
        self.audit.append(
            AuditAction.KILL_SWITCH_CHANGED,
            "system",
            self._key(value.get("scope", SCOPE_SYSTEM), value.get("target", "")),
            actor=actor,
            payload={"action": action, **value},
        )
        if self.outbox is not None:
            self.outbox.emit(
                EventType.KILL_SWITCH_CHANGED,
                {"action": action, "active": value.get("active"), "reason": value.get("reason"),
                 "scope": value.get("scope"), "target": value.get("target"), "actor": actor},
                occurred_at=moment,
            )
