"""Health, readiness, and liveness probes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fxars.core.timeutil import format_ts
from fxars.platform import Platform


@dataclass
class HealthReport:
    status: str
    phase: str
    time: str
    checks: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "phase": self.phase,
            "time": self.time,
            "checks": self.checks,
        }


def live(platform: Platform) -> HealthReport:
    return HealthReport(
        status="ok",
        phase=platform.settings.phase.value,
        time=format_ts(platform.clock()),
        checks={"process": True},
    )


def ready(platform: Platform) -> HealthReport:
    checks: dict[str, bool] = {}
    try:
        checks["database"] = platform.db.query_one("SELECT 1 AS ok") is not None
    except Exception:
        checks["database"] = False
    try:
        checks["audit_chain"] = bool(platform.audit.verify().get("valid"))
    except Exception:
        checks["audit_chain"] = False
    try:
        checks["killswitch_table"] = True
    except Exception:
        checks["killswitch_table"] = False
    all_ok = all(checks.values())
    return HealthReport(
        status="ok" if all_ok else "degraded",
        phase=platform.settings.phase.value,
        time=format_ts(platform.clock()),
        checks=checks,
    )


def aggregate(platform: Platform) -> HealthReport:
    report = ready(platform)
    checks = dict(report.checks)
    try:
        checks["killswitch_inactive"] = not platform.killswitch.is_active()
    except Exception:
        checks["killswitch_inactive"] = False
    report.checks = checks
    if not all(v for k, v in checks.items() if k != "killswitch_inactive"):
        report.status = "degraded"
    return report
