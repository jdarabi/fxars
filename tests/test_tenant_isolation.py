"""آزمون جداسازی مستاجر (فاز ۷): داده‌های هر tenant فقط برای خودش دیده می‌شود."""

from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlparse

from fxars.api.server import ApiApp, ApiRequest
from fxars.core.errors import ValidationError
from fxars.domain.enums import DecisionAction, Direction, OrderStatus, Role
from fxars.domain.models import Decision, OrderIntent, Tenant

from tests.helpers import ANALYST_PASSWORD, make_env

BETA_PASSWORD = "BetaPass123!"


class TenantIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = make_env(bars=600, users=True)
        cls.platform = cls.env.platform
        cls.app = ApiApp(cls.platform)
        cls.counter = 0
        moment = cls.platform.clock()
        cls.platform.tenants.save(Tenant(tenant_id="beta", name="Beta", active=True, created_at=moment))
        cls.beta_user, _ = cls.platform.identity.create_user(
            "beta_analyst", Role.ANALYST, BETA_PASSWORD, tenant_id="beta",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.env.close()

    def call(self, method: str, path: str, body: dict | None = None, *, token: str | None = None,
             idempotency: str | None = "auto") -> tuple[int, dict]:
        self.__class__.counter += 1
        parsed = urlparse(path)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if method == "POST" and token is not None and idempotency is not None:
            headers["Idempotency-Key"] = idempotency if idempotency != "auto" else f"tenant-{self.counter}"
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

    def _build_scenario(self, tenant_id: str, run_id: str):
        outcome = self.platform.analysis_engine.analyze(
            instrument=self.env.instrument, timeframe="H1", candles=self.env.candles,
            as_of=self.env.as_of, run_id=run_id,
        )
        decision = Decision(
            action=DecisionAction.LONG, direction=Direction.LONG, score=0.5, confidence_raw=0.5,
            family_scores={"STRUCTURE": 0.5}, conflicts=(), coverage=0.5, stability=1.0,
            reasons=("tenant-test",), evidence_ids=("ev_tenant",), strength=0.6,
        )
        built = self.platform.scenario_builder.build(
            outcome, decision, run_id=run_id, rules_version="v1", tenant_id=tenant_id,
        )
        self.assertIsNotNone(built.scenario)
        scenario = built.scenario
        self.platform.scenarios.save(scenario)
        return scenario

    # ------------------------------------------------------------------
    def test_identity_requires_known_tenant(self) -> None:
        with self.assertRaises(ValidationError):
            self.platform.identity.create_user("ghost", Role.ANALYST, "GhostPass123!", tenant_id="missing")

    def test_analysis_and_scenario_are_isolated(self) -> None:
        alpha_token = self.login("analyst", ANALYST_PASSWORD)
        beta_token = self.login("beta_analyst", BETA_PASSWORD)
        alpha_scenario = self._build_scenario("default", "ar_tenant_alpha")
        beta_scenario = self._build_scenario("beta", "ar_tenant_beta")

        _, alpha_list = self.call("GET", "/api/v1/scenarios", token=alpha_token)
        _, beta_list = self.call("GET", "/api/v1/scenarios", token=beta_token)
        alpha_ids = {item["scenario_id"] for item in alpha_list["items"]}
        beta_ids = {item["scenario_id"] for item in beta_list["items"]}
        self.assertIn(alpha_scenario.scenario_id, alpha_ids)
        self.assertNotIn(beta_scenario.scenario_id, alpha_ids)
        self.assertIn(beta_scenario.scenario_id, beta_ids)
        self.assertNotIn(alpha_scenario.scenario_id, beta_ids)
        self.assertEqual(sum(beta_list["summary"].values()), len(beta_ids))

        status, _ = self.call("GET", f"/api/v1/scenarios/{alpha_scenario.scenario_id}", token=beta_token)
        self.assertEqual(status, 404)
        status, _ = self.call(
            "POST", f"/api/v1/scenarios/{alpha_scenario.scenario_id}/evaluate",
            {}, token=beta_token, idempotency="cross-eval",
        )
        self.assertEqual(status, 404)
        status, _ = self.call(
            "POST", f"/api/v1/scenarios/{alpha_scenario.scenario_id}/transition",
            {"status": "WATCH", "reason": "cross"}, token=beta_token, idempotency="cross-transition",
        )
        self.assertEqual(status, 404)

    def test_analysis_runs_are_isolated_and_recomputed_per_tenant(self) -> None:
        alpha_token = self.login("analyst", ANALYST_PASSWORD)
        beta_token = self.login("beta_analyst", BETA_PASSWORD)
        body = {"instrument_id": "EURUSD", "timeframe": "H1", "as_of": self.env.as_of.isoformat()}

        status, alpha = self.call("POST", "/api/v1/analysis-runs", body, token=alpha_token,
                                  idempotency="tenant-analysis-alpha")
        self.assertEqual(status, 200, alpha)
        status, beta = self.call("POST", "/api/v1/analysis-runs", body, token=beta_token,
                                 idempotency="tenant-analysis-beta")
        self.assertEqual(status, 200, beta)
        self.assertNotEqual(alpha["run"]["run_id"], beta["run"]["run_id"])
        self.assertEqual(alpha["run"]["tenant_id"], "default")
        self.assertEqual(beta["run"]["tenant_id"], "beta")

        status, _ = self.call("GET", f"/api/v1/analysis-runs/{alpha['run']['run_id']}", token=beta_token)
        self.assertEqual(status, 404)
        _, listing = self.call("GET", "/api/v1/analysis-runs", token=beta_token)
        self.assertTrue(all(item["tenant_id"] == "beta" for item in listing["items"]))

    def test_risk_decisions_are_isolated(self) -> None:
        alpha_scenario = self._build_scenario("default", "ar_tenant_risk_alpha")
        beta_token = self.login("beta_analyst", BETA_PASSWORD)
        alpha_token = self.login("analyst", ANALYST_PASSWORD)
        account = {"account_id": "acc-1", "currency": "USD", "balance": "10000", "equity": "10000",
                   "free_margin": "9000", "positions": []}
        status, _ = self.call(
            "POST", "/api/v1/risk/evaluate",
            {"scenario_id": alpha_scenario.scenario_id, "account": account},
            token=beta_token, idempotency="cross-risk",
        )
        self.assertEqual(status, 404)
        status, decision = self.call(
            "POST", "/api/v1/risk/evaluate",
            {"scenario_id": alpha_scenario.scenario_id, "account": account},
            token=alpha_token, idempotency="own-risk",
        )
        self.assertEqual(status, 200, decision)
        _, beta_decisions = self.call("GET", "/api/v1/risk/decisions", token=beta_token)
        self.assertEqual(beta_decisions["items"], [])

    def test_order_intent_repository_scoped(self) -> None:
        moment = self.platform.clock()
        base = dict(
            client_order_id="tenant-order-alpha", risk_decision_id="rd-alpha", instrument_id="EURUSD",
            side="BUY", order_type="MARKET", volume="0.10", stop_loss="1.1000", take_profit=None,
            created_at=moment, status="INTENT_CREATED", phase="DEMO", tenant_id="default",
        )
        alpha = OrderIntent(intent_id="oi_alpha", **base)
        beta = OrderIntent(intent_id="oi_beta", **{**base, "client_order_id": "tenant-order-beta",
                                                   "tenant_id": "beta"})
        self.platform.orders.save_intent(alpha)
        self.platform.orders.save_intent(beta)

        self.assertIsNone(self.platform.orders.get_intent_for_tenant("oi_alpha", "beta"))
        self.assertEqual(self.platform.orders.get_intent_for_tenant("oi_beta", "beta").intent_id, "oi_beta")
        beta_rows = self.platform.orders.list_intents_by_status(OrderStatus.INTENT_CREATED, tenant_id="beta")
        self.assertEqual([row.intent_id for row in beta_rows], ["oi_beta"])


if __name__ == "__main__":
    unittest.main()
