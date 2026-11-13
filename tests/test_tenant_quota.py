"""آزمون پلن اشتراک و سهمیه مستاجر (فاز ۷)."""

from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlparse

from fxars.api.server import ApiApp, ApiRequest
from fxars.core.errors import QuotaExceededError, TenantInactiveError
from fxars.domain.enums import Direction, Role, ScenarioStatus
from fxars.domain.models import Scenario, Tenant
from fxars.tenancy.plans import PLANS, resolve_limits

from tests.helpers import make_env

BETA_PASSWORD = "BetaPass123!"


class PlanCatalogTests(unittest.TestCase):
    def test_unknown_plan_falls_back_to_basic(self) -> None:
        self.assertEqual(resolve_limits("nope"), resolve_limits("basic"))
        self.assertNotEqual(PLANS["basic"].analysis_runs_per_day, -1)
        self.assertEqual(PLANS["enterprise"].analysis_runs_per_day, -1)

    def test_overrides_apply_and_unknown_keys_ignored(self) -> None:
        limits = resolve_limits("basic", {"max_users": 7, "bogus": 99})
        self.assertEqual(limits["max_users"], 7)
        self.assertNotIn("bogus", limits)


class TenantQuotaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = make_env(bars=600, users=True)
        cls.platform = cls.env.platform
        cls.app = ApiApp(cls.platform)
        cls.counter = 0
        cls.platform.tenants.save(
            Tenant(tenant_id="beta", name="Beta", active=True, created_at=cls.platform.clock(), plan="basic")
        )
        cls.platform.identity.create_user("beta_analyst", Role.ANALYST, BETA_PASSWORD, tenant_id="beta")
        admin_user, _ = cls.platform.identity.create_user(
            "tenant_admin", Role.ADMIN, "TenantAdminPass123!", totp_enabled=True,
        )
        cls.admin_token = cls.platform.identity.start_session(admin_user).token

    @classmethod
    def tearDownClass(cls) -> None:
        cls.env.close()

    def call(self, method: str, path: str, body: dict | None = None, *, token: str | None = None,
             idempotency: str | None = "auto") -> tuple[int, dict]:
        self.__class__.counter += 1
        parsed = urlparse(path)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if method == "POST" and token is not None and idempotency is not None:
            headers["Idempotency-Key"] = idempotency if idempotency != "auto" else f"quota-{self.counter}"
        request = ApiRequest(
            method=method, path=parsed.path, query=parse_qs(parsed.query),
            headers={key.lower(): value for key, value in headers.items()},
            body=json.dumps(body).encode("utf-8") if body is not None else b"",
            ip="127.0.0.1",
        )
        response = self.app.handle(request)
        payload = json.loads(response.body.decode("utf-8")) if response.body else {}
        return response.status, payload

    def login(self, username: str, password: str) -> str:
        status, payload = self.call(
            "POST", "/api/v1/auth/login",
            {"username": username, "password": password}, token=None,
        )
        self.assertEqual(status, 200, payload)
        return payload["token"]

    def _set_beta_overrides(self, overrides: dict[str, int]) -> None:
        tenant = self.platform.tenants.get("beta")
        self.platform.tenants.save(Tenant(
            tenant_id=tenant.tenant_id, name=tenant.name, active=tenant.active,
            created_at=tenant.created_at, plan=tenant.plan, quota_overrides=overrides,
        ))

    # ------------------------------------------------------------------
    def test_default_tenant_is_not_quota_limited(self) -> None:
        snapshot = self.platform.quota.snapshot("default")
        self.assertEqual(snapshot["plan"], "enterprise")
        self.assertEqual(snapshot["limits"]["max_users"], -1)
        self.assertEqual(snapshot["limits"]["analysis_runs_per_day"], -1)

    def test_user_quota_enforced_for_commercial_tenant(self) -> None:
        self._set_beta_overrides({"max_users": 2})
        self.platform.identity.create_user("beta_second", Role.ANALYST, "SecondPass123!", tenant_id="beta")
        with self.assertRaises(QuotaExceededError) as ctx:
            self.platform.identity.create_user("beta_third", Role.ANALYST, "ThirdPass123!", tenant_id="beta")
        self.assertEqual(ctx.exception.details["quota"], "max_users")
        self.assertEqual(ctx.exception.details["used"], 2)

    def test_analysis_quota_blocks_new_runs(self) -> None:
        beta_token = self.login("beta_analyst", BETA_PASSWORD)
        body = {"instrument_id": "EURUSD", "timeframe": "H1", "as_of": self.env.as_of.isoformat()}
        self._set_beta_overrides({"analysis_runs_per_day": 0})
        status, payload = self.call(
            "POST", "/api/v1/analysis-runs", body, token=beta_token, idempotency="quota-analysis",
        )
        self.assertEqual(status, 429, payload)
        self.assertEqual(payload["error"]["code"], "QUOTA_EXCEEDED")

    def test_analysis_quota_counts_and_limits(self) -> None:
        self._set_beta_overrides({"analysis_runs_per_day": 2})
        before = self.platform.quota.usage("beta").analyses_today
        self.assertGreaterEqual(before, 0)
        self.platform.run_analysis("EURUSD", "H1", as_of=self.env.as_of, tenant_id="beta", actor="beta_analyst")
        usage = self.platform.quota.usage("beta")
        self.assertGreaterEqual(usage.analyses_today, before + 1)

    def test_live_scenario_quota(self) -> None:
        moment = self.platform.clock()
        self.platform.scenarios.save(Scenario(
            scenario_id="sc_quota_live", instrument_id="EURUSD", timeframe="H1",
            direction=Direction.LONG, status=ScenarioStatus.WATCH,
            entry_condition={"level": "1.1"}, invalidation_condition={"level": "1.0"},
            stop_logic={"level": "1.0"}, target_logic=(), expiry_at=moment,
            evidence_ids=(), analysis_run_id="ar_quota_live", decision_explanation="",
            created_at=moment, updated_at=moment, rules_version="v1", config_hash="",
            tenant_id="beta",
        ))
        self._set_beta_overrides({"live_scenarios": 1})
        used = self.platform.quota.usage("beta").live_scenarios
        self.assertGreaterEqual(used, 1)
        self._set_beta_overrides({"live_scenarios": used})
        with self.assertRaises(QuotaExceededError):
            self.platform.quota.check_live_scenario("beta")
        self._set_beta_overrides({"live_scenarios": used + 1})
        self.platform.quota.check_live_scenario("beta")

    def test_inactive_tenant_is_blocked(self) -> None:
        tenant = self.platform.tenants.get("beta")
        self.platform.tenants.save(Tenant(
            tenant_id=tenant.tenant_id, name=tenant.name, active=False,
            created_at=tenant.created_at, plan=tenant.plan,
            quota_overrides=tenant.quota_overrides,
        ))
        try:
            with self.assertRaises(TenantInactiveError):
                self.platform.quota.limits("beta")
        finally:
            self.platform.tenants.save(Tenant(
                tenant_id=tenant.tenant_id, name=tenant.name, active=True,
                created_at=tenant.created_at, plan=tenant.plan,
                quota_overrides=tenant.quota_overrides,
            ))

    def test_tenant_endpoints_and_admin_update(self) -> None:
        beta_token = self.login("beta_analyst", BETA_PASSWORD)
        admin_token = self.__class__.admin_token

        status, own = self.call("GET", "/api/v1/tenant", token=beta_token)
        self.assertEqual(status, 200, own)
        self.assertEqual(own["tenant"]["tenant_id"], "beta")
        self.assertIn("limits", own)
        self.assertIn("usage", own)

        status, _ = self.call("GET", "/api/v1/tenants", token=beta_token)
        self.assertEqual(status, 403)

        status, updated = self.call(
            "POST", "/api/v1/tenants/beta", {"plan": "pro"}, token=admin_token,
            idempotency="tenant-plan-beta",
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["plan"], "pro")
        self.assertEqual(self.platform.tenants.get("beta").plan, "pro")

        status, payload = self.call(
            "POST", "/api/v1/tenants/beta", {"plan": "gold"}, token=admin_token,
            idempotency="tenant-plan-invalid",
        )
        self.assertEqual(status, 400, payload)
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

        status, _ = self.call("POST", "/api/v1/tenants/ghost", {"plan": "pro"}, token=admin_token,
                              idempotency="tenant-plan-ghost")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
