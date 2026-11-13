"""چرخه قفل ریسک — بخش ۳-۳ سند تکمیلی ۱.۱.

    NORMAL → WARNING → LOCKED_DAILY → LOCKED_WEEKLY → KILL_SWITCH → MANUAL_REVIEW

WARNING هشدار است؛ LOCKED_* و KILL_SWITCH ارسال سفارش را متوقف می‌کنند.
بازگشت از LOCKED_* فقط پس از بازبینی دستی و با دلیل ثبت‌شده مجاز است.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from fxars.audit.audit import AuditAction
from fxars.core.errors import ValidationError
from fxars.core.numerics import to_decimal
from fxars.core.timeutil import format_ts, utcnow
from fxars.domain.enums import RiskLockState
from fxars.storage.repositories import SystemStateRepository

KEY = "risk_lock"

ALLOWED: dict[RiskLockState, set[RiskLockState]] = {
    RiskLockState.NORMAL: {
        RiskLockState.WARNING,
        RiskLockState.LOCKED_DAILY,
        RiskLockState.LOCKED_WEEKLY,
        RiskLockState.KILL_SWITCH,
        RiskLockState.MANUAL_REVIEW,
    },
    RiskLockState.WARNING: {
        RiskLockState.NORMAL,
        RiskLockState.LOCKED_DAILY,
        RiskLockState.LOCKED_WEEKLY,
        RiskLockState.KILL_SWITCH,
        RiskLockState.MANUAL_REVIEW,
    },
    RiskLockState.LOCKED_DAILY: {
        RiskLockState.LOCKED_DAILY,
        RiskLockState.LOCKED_WEEKLY,
        RiskLockState.KILL_SWITCH,
        RiskLockState.MANUAL_REVIEW,
    },
    RiskLockState.LOCKED_WEEKLY: {
        RiskLockState.LOCKED_WEEKLY,
        RiskLockState.KILL_SWITCH,
        RiskLockState.MANUAL_REVIEW,
    },
    RiskLockState.KILL_SWITCH: {
        RiskLockState.KILL_SWITCH,
        RiskLockState.MANUAL_REVIEW,
    },
    RiskLockState.MANUAL_REVIEW: {
        RiskLockState.NORMAL,
        RiskLockState.LOCKED_DAILY,
        RiskLockState.LOCKED_WEEKLY,
        RiskLockState.KILL_SWITCH,
        RiskLockState.MANUAL_REVIEW,
    },
}

BLOCKING_STATES = {
    RiskLockState.LOCKED_DAILY,
    RiskLockState.LOCKED_WEEKLY,
    RiskLockState.KILL_SWITCH,
    RiskLockState.MANUAL_REVIEW,
}


@dataclass(frozen=True)
class RiskLockThresholds:
    daily_warn: Decimal = Decimal("0.05")
    daily_limit: Decimal = Decimal("0.08")
    weekly_limit: Decimal = Decimal("0.15")
    drawdown_warn: Decimal = Decimal("0.08")
    drawdown_stop: Decimal = Decimal("0.15")

    @classmethod
    def from_risk_policy(cls, policy) -> RiskLockThresholds:
        return cls(
            daily_warn=policy.drawdown_warn / 2 if policy.drawdown_warn > 0 else Decimal("0.025"),
            daily_limit=policy.daily_loss_limit,
            weekly_limit=min(Decimal("1"), policy.daily_loss_limit * 3),
            drawdown_warn=policy.drawdown_warn,
            drawdown_stop=policy.drawdown_stop,
        )


@dataclass(frozen=True)
class RiskLockDecision:
    state: RiskLockState
    previous: RiskLockState
    changed: bool
    reasons: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    evaluated_at: datetime | None = None

    @property
    def blocks_orders(self) -> bool:
        return self.state in BLOCKING_STATES

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "previous": self.previous.value,
            "changed": self.changed,
            "blocks_orders": self.blocks_orders,
            "reasons": list(self.reasons),
            "metrics": self.metrics,
            "evaluated_at": format_ts(self.evaluated_at) if self.evaluated_at else None,
        }


class RiskLockMachine:
    def __init__(
        self,
        state: SystemStateRepository,
        audit,
        *,
        thresholds: RiskLockThresholds | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.state = state
        self.audit = audit
        self.thresholds = thresholds or RiskLockThresholds()
        self.clock = clock or utcnow

    def status(self) -> dict[str, Any]:
        value = self.state.get(KEY, {})
        if not value:
            return {
                "state": RiskLockState.NORMAL.value,
                "updated_at": None,
                "reasons": [],
                "history": [],
            }
        value.setdefault("state", RiskLockState.NORMAL.value)
        return value

    def current(self) -> RiskLockState:
        try:
            return RiskLockState(self.status().get("state", "NORMAL"))
        except ValueError:
            return RiskLockState.MANUAL_REVIEW

    def evaluate(
        self,
        *,
        daily_loss: Any = 0,
        weekly_loss: Any = 0,
        drawdown: Any = 0,
        kill_switch_active: bool = False,
        manual_review: bool = False,
        now: datetime | None = None,
    ) -> RiskLockDecision:
        previous = self.current()
        daily = to_decimal(daily_loss)
        weekly = to_decimal(weekly_loss)
        draw = to_decimal(drawdown)
        reasons: list[str] = []
        target = RiskLockState.NORMAL
        if kill_switch_active:
            target = RiskLockState.KILL_SWITCH
            reasons.append("Kill Switch فعال است.")
        elif manual_review:
            target = RiskLockState.MANUAL_REVIEW
            reasons.append("حساب در بازبینی دستی است.")
        elif weekly >= self.thresholds.weekly_limit:
            target = RiskLockState.LOCKED_WEEKLY
            reasons.append(f"زیان هفتگی {float(weekly):.2%} به سقف رسیده است.")
        elif daily >= self.thresholds.daily_limit:
            target = RiskLockState.LOCKED_DAILY
            reasons.append(f"زیان روزانه {float(daily):.2%} به سقف رسیده است.")
        elif draw >= self.thresholds.drawdown_stop:
            target = RiskLockState.LOCKED_DAILY
            reasons.append(f"افت سرمایه {float(draw):.2%} از حد توقف گذشته است.")
        elif daily >= self.thresholds.daily_warn or draw >= self.thresholds.drawdown_warn:
            target = RiskLockState.WARNING
            reasons.append("آستانه هشدار زیان/افت سرمایه عبور شده است.")

        # قفل‌های قبلی به‌صورت خودکار باز نمی‌شوند؛ فقط بازبینی دستی.
        if previous in (RiskLockState.LOCKED_DAILY, RiskLockState.LOCKED_WEEKLY) and target in (
            RiskLockState.NORMAL,
            RiskLockState.WARNING,
        ):
            target = previous
            reasons.append("قفل قبلی تا بازبینی دستی حفظ می‌شود.")
        if previous is RiskLockState.KILL_SWITCH and target is not RiskLockState.KILL_SWITCH:
            target = RiskLockState.KILL_SWITCH
            reasons.append("Kill Switch تا غیرفعال‌سازی رسمی فعال می‌ماند.")
        if previous is RiskLockState.MANUAL_REVIEW and target is not RiskLockState.KILL_SWITCH:
            target = RiskLockState.MANUAL_REVIEW
            reasons.append("بازبینی دستی تا آزادسازی رسمی ادامه دارد.")
        if target not in ALLOWED.get(previous, set()):
            target = previous

        decision = RiskLockDecision(
            state=target,
            previous=previous,
            changed=target is not previous,
            reasons=tuple(reasons),
            metrics={
                "daily_loss": str(daily),
                "weekly_loss": str(weekly),
                "drawdown": str(draw),
                "thresholds": {
                    "daily_warn": str(self.thresholds.daily_warn),
                    "daily_limit": str(self.thresholds.daily_limit),
                    "weekly_limit": str(self.thresholds.weekly_limit),
                    "drawdown_warn": str(self.thresholds.drawdown_warn),
                    "drawdown_stop": str(self.thresholds.drawdown_stop),
                },
            },
            evaluated_at=now or self.clock(),
        )
        if decision.changed:
            self._persist(decision, actor="system")
        return decision

    def manual_review(self, *, actor: str, reason: str, release: bool = False) -> dict[str, Any]:
        if not reason.strip():
            raise ValidationError("تغییر بازبینی ریسک نیازمند دلیل است.")
        previous = self.current()
        target = RiskLockState.NORMAL if release else RiskLockState.MANUAL_REVIEW
        if target not in ALLOWED.get(previous, set()):
            raise ValidationError(
                f"گذار وضعیت قفل ریسک از {previous.value} به {target.value} مجاز نیست."
            )
        moment = self.clock()
        decision = RiskLockDecision(
            state=target,
            previous=previous,
            changed=True,
            reasons=(reason,),
            metrics={"actor": actor, "manual": True},
            evaluated_at=moment,
        )
        self._persist(decision, actor=actor)
        return decision.to_dict()

    def _persist(self, decision: RiskLockDecision, *, actor: str) -> None:
        previous_payload = self.status()
        history = list(previous_payload.get("history", []))[-19:]
        history.append(
            {
                "from": decision.previous.value,
                "to": decision.state.value,
                "at": format_ts(decision.evaluated_at) if decision.evaluated_at else None,
                "reasons": list(decision.reasons),
                "actor": actor,
            }
        )
        payload = {
            "state": decision.state.value,
            "updated_at": format_ts(decision.evaluated_at) if decision.evaluated_at else None,
            "reasons": list(decision.reasons),
            "metrics": decision.metrics,
            "history": history,
        }
        self.state.set(KEY, payload, actor)
        self.audit.append(
            AuditAction.RISK_LOCK_CHANGED,
            "risk_lock",
            KEY,
            actor=actor,
            payload={
                "from": decision.previous.value,
                "to": decision.state.value,
                "reasons": list(decision.reasons),
                "metrics": decision.metrics,
            },
        )
