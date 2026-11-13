"""اعمال سهمیه اشتراک در مرزهای سرویس (فاز ۷).

هر بررسی یا مجاز است یا ``QuotaExceededError`` (HTTP 429) با جزئیات سقف و مصرف.
مستاجر غیرفعال با ``TenantInactiveError`` (HTTP 403) مسدود می‌شود.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from fxars.core.errors import NotFoundError, QuotaExceededError, TenantInactiveError
from fxars.domain.models import Tenant
from fxars.tenancy.plans import UNLIMITED, resolve_limits

_LIVE_STATUSES = ("DRAFT", "WATCH", "ARMED", "TRIGGERED")


@dataclass(frozen=True, slots=True)
class QuotaUsage:
    users: int
    analyses_today: int
    live_scenarios: int

    def to_dict(self) -> dict[str, int]:
        return {
            "users": self.users,
            "analyses_today": self.analyses_today,
            "live_scenarios": self.live_scenarios,
        }


class QuotaService:
    def __init__(
        self,
        *,
        tenants,
        users,
        analyses,
        scenarios,
        clock: Callable[[], datetime],
    ) -> None:
        self.tenants = tenants
        self.users = users
        self.analyses = analyses
        self.scenarios = scenarios
        self.clock = clock

    def tenant(self, tenant_id: str) -> Tenant:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"مستاجر {tenant_id} یافت نشد.", details={"tenant_id": tenant_id})
        if not tenant.active:
            raise TenantInactiveError(
                f"مستاجر {tenant_id} غیرفعال است.",
                details={"tenant_id": tenant_id},
            )
        return tenant

    def limits(self, tenant_id: str) -> dict[str, int]:
        tenant = self.tenant(tenant_id)
        return resolve_limits(tenant.plan, tenant.quota_overrides)

    def usage(self, tenant_id: str, now: datetime | None = None) -> QuotaUsage:
        moment = now or self.clock()
        day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        by_status = self.scenarios.count_by_status(tenant_id=tenant_id)
        return QuotaUsage(
            users=self.users.count_by_tenant(tenant_id),
            analyses_today=self.analyses.count_since(tenant_id, day_start),
            live_scenarios=sum(by_status.get(status, 0) for status in _LIVE_STATUSES),
        )

    def check_user(self, tenant_id: str) -> None:
        self._check(tenant_id, "max_users", self.usage(tenant_id).users, "کاربر")

    def check_analysis(self, tenant_id: str) -> None:
        self._check(tenant_id, "analysis_runs_per_day", self.usage(tenant_id).analyses_today, "تحلیل روزانه")

    def check_live_scenario(self, tenant_id: str) -> None:
        self._check(tenant_id, "live_scenarios", self.usage(tenant_id).live_scenarios, "سناریوی فعال")

    def snapshot(self, tenant_id: str) -> dict[str, object]:
        tenant = self.tenant(tenant_id)
        return {
            "tenant": tenant.to_dict(),
            "plan": tenant.plan,
            "limits": resolve_limits(tenant.plan, tenant.quota_overrides),
            "usage": self.usage(tenant_id).to_dict(),
        }

    def _check(self, tenant_id: str, key: str, used: int, label: str) -> None:
        limit = self.limits(tenant_id)[key]
        if limit == UNLIMITED or used < limit:
            return
        raise QuotaExceededError(
            f"سهمیه {label} این مستاجر تکمیل شده است ({used}/{limit}).",
            details={"tenant_id": tenant_id, "quota": key, "limit": limit, "used": used},
        )
