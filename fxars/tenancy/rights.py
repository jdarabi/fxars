"""حقوق داده مستاجر (فاز ۷): خروجی داده و گزارش نگهداری، بدون حذف خودکار."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fxars.core.timeutil import format_ts


class DataRightsService:
    def __init__(
        self,
        *,
        analyses,
        scenarios,
        decisions,
        orders,
        users,
        clock: Callable[[], datetime],
    ) -> None:
        self.analyses = analyses
        self.scenarios = scenarios
        self.decisions = decisions
        self.orders = orders
        self.users = users
        self.clock = clock

    def export(self, tenant_id: str, *, limit: int = 1000) -> dict[str, object]:
        """بسته JSON داده‌های مستاجر؛ بدون هش رمز، secret یا توکن."""
        users = [
            {
                "user_id": user.user_id,
                "username": user.username,
                "role": user.role.value,
                "active": user.active,
                "created_at": format_ts(user.created_at),
                "tenant_id": user.tenant_id,
            }
            for user in self.users.list()
            if user.tenant_id == tenant_id
        ]
        analyses = [run.to_dict() for run in self.analyses.list_runs(tenant_id=tenant_id, limit=limit)]
        scenarios = [item.to_dict() for item in self.scenarios.list(tenant_id=tenant_id, limit=limit)]
        decisions = [item.to_dict() for item in self.decisions.list(tenant_id=tenant_id, limit=limit)]
        orders = [item.to_dict() for item in self.orders.list_by_tenant(tenant_id, limit=limit)]
        return {
            "tenant_id": tenant_id,
            "generated_at": format_ts(self.clock()),
            "counts": {
                "users": len(users),
                "analysis_runs": len(analyses),
                "scenarios": len(scenarios),
                "risk_decisions": len(decisions),
                "order_intents": len(orders),
            },
            "users": users,
            "analysis_runs": analyses,
            "scenarios": scenarios,
            "risk_decisions": decisions,
            "order_intents": orders,
        }

    def retention_report(self, tenant_id: str) -> dict[str, object]:
        """سیاست نگهداری و حجم فعلی؛ حذف فقط با تصمیم صریح اپراتور انجام می‌شود."""
        scenarios = self.scenarios.count_by_status(tenant_id=tenant_id)
        counts = {
            "users": self.users.count_by_tenant(tenant_id),
            "analysis_runs": self.analyses.count_by_tenant(tenant_id),
            "scenarios": sum(scenarios.values()),
            "risk_decisions": self.decisions.count_by_tenant(tenant_id),
            "order_intents": self.orders.count_by_tenant(tenant_id),
        }
        return {
            "tenant_id": tenant_id,
            "generated_at": format_ts(self.clock()),
            "policy": {
                "raw_payloads": "مطابق retention_days هر DataSource",
                "sessions": "حذف پس از انقضا (purge_expired)",
                "idempotency_keys": "قابل پاک‌سازی با cutoff در IdempotencyRepository",
                "tenant_data": "حذف دسته‌ای نیازمند تأیید صریح اپراتور و پشتیبان‌گیری است.",
            },
            "counts": counts,
        }
