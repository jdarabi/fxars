"""کاتالوگ پلن‌های اشتراک و سقف‌های پیش‌فرض هر پلن."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

UNLIMITED = -1

QUOTA_KEYS = ("max_users", "analysis_runs_per_day", "live_scenarios")


@dataclass(frozen=True, slots=True)
class Plan:
    plan_id: str
    title: str
    max_users: int
    analysis_runs_per_day: int
    live_scenarios: int

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "max_users": self.max_users,
            "analysis_runs_per_day": self.analysis_runs_per_day,
            "live_scenarios": self.live_scenarios,
        }


PLANS: dict[str, Plan] = {
    "basic": Plan("basic", "پایه", max_users=3, analysis_runs_per_day=500, live_scenarios=50),
    "pro": Plan("pro", "حرفه‌ای", max_users=20, analysis_runs_per_day=5000, live_scenarios=500),
    "enterprise": Plan("enterprise", "سازمانی", max_users=UNLIMITED, analysis_runs_per_day=UNLIMITED,
                       live_scenarios=UNLIMITED),
}

PLAN_ORDER = tuple(PLANS)

DEFAULT_PLAN = "basic"


def resolve_limits(plan_id: str, overrides: Mapping[str, int] | None = None) -> dict[str, int]:
    """سقف‌های مؤثر پلن؛ پلن ناشناخته به پایه (محافظه‌کارانه) فروکاسته می‌شود."""
    plan = PLANS.get(plan_id, PLANS[DEFAULT_PLAN])
    limits = {key: int(getattr(plan, key)) for key in QUOTA_KEYS}
    for key, value in (overrides or {}).items():
        if key in limits:
            limits[key] = int(value)
    return limits
