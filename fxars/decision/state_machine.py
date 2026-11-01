"""ماشین حالت سناریو با گذارهای صریح و ثبت اجباری رویداد.

تغییر مستقیم status ممنوع است؛ هر گذار با actor، دلیل، زمان، نسخه قواعد و مرجع داده
ثبت می‌شود (بخش ۸-۲ سند).
"""

from __future__ import annotations

from datetime import datetime

from fxars.core.errors import ScenarioTransitionError
from fxars.core.ids import stable_id
from fxars.core.timeutil import utcnow
from fxars.domain.enums import ScenarioStatus
from fxars.domain.models import Scenario, ScenarioTransition

# from_status -> {to_status: event_name}
ALLOWED: dict[ScenarioStatus, dict[ScenarioStatus, str]] = {
    ScenarioStatus.DRAFT: {
        ScenarioStatus.WATCH: "evidence_sufficient",
        ScenarioStatus.INVALIDATED: "invalidated",
        ScenarioStatus.EXPIRED: "expired",
        ScenarioStatus.REJECTED: "risk_rejected",
    },
    ScenarioStatus.WATCH: {
        ScenarioStatus.ARMED: "preconditions_met",
        ScenarioStatus.INVALIDATED: "invalidated",
        ScenarioStatus.EXPIRED: "expired",
        ScenarioStatus.REJECTED: "risk_rejected",
    },
    ScenarioStatus.ARMED: {
        ScenarioStatus.TRIGGERED: "triggered",
        ScenarioStatus.INVALIDATED: "invalidated",
        ScenarioStatus.EXPIRED: "expired",
        ScenarioStatus.REJECTED: "risk_rejected",
    },
    ScenarioStatus.TRIGGERED: {
        ScenarioStatus.EXPIRED: "entry_conditions_lost",
        ScenarioStatus.INVALIDATED: "invalidated",
        ScenarioStatus.REJECTED: "risk_rejected",
        ScenarioStatus.WATCH: "rearmed",
    },
}


def can_transition(current: ScenarioStatus, target: ScenarioStatus) -> bool:
    return target in ALLOWED.get(current, {})


class ScenarioStateMachine:
    def __init__(self, rules_version: str) -> None:
        self.rules_version = rules_version

    def transition(
        self,
        scenario: Scenario,
        target: ScenarioStatus,
        *,
        actor: str,
        reason: str,
        occurred_at: datetime | None = None,
        data_ref: str = "",
        correlation_id: str = "",
        event: str | None = None,
    ) -> tuple[Scenario, ScenarioTransition]:
        when = occurred_at or utcnow()
        if scenario.status.is_terminal:
            raise ScenarioTransitionError(
                f"سناریو در وضعیت پایانی {scenario.status.value} است و تغییر نمی‌کند.",
                details={"scenario_id": scenario.scenario_id, "status": scenario.status.value},
            )
        allowed_events = ALLOWED.get(scenario.status, {})
        if target not in allowed_events:
            raise ScenarioTransitionError(
                f"گذار از {scenario.status.value} به {target.value} مجاز نیست.",
                details={
                    "scenario_id": scenario.scenario_id,
                    "from": scenario.status.value,
                    "to": target.value,
                    "allowed": [status.value for status in allowed_events],
                },
            )
        if not reason.strip():
            raise ScenarioTransitionError("ثبت دلیل گذار الزامی است.", details={"scenario_id": scenario.scenario_id})

        transition = ScenarioTransition(
            transition_id=stable_id("tr", scenario.scenario_id, scenario.status.value, target.value, when, reason, length=24),
            scenario_id=scenario.scenario_id,
            from_status=scenario.status,
            to_status=target,
            event=event or allowed_events[target],
            actor=actor,
            reason=reason,
            occurred_at=when,
            rules_version=self.rules_version,
            data_ref=data_ref,
            correlation_id=correlation_id,
        )
        updated = scenario.with_status(target, when=when)
        return updated, transition
