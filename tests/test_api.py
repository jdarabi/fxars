"""آزمون API درون‌فرآیندی: احراز هویت، RBAC، Idempotency و قرارداد خطا."""

from __future__ import annotations

import json
import unittest

from fxars.api.server import ApiApp, ApiRequest
from fxars.identity.totp import totp

from tests.helpers import ADMIN_PASSWORD, ANALYST_PASSWORD, make_env


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = make_env(bars=600, users=True)
        cls.app = ApiApp(cls.env.platform)
        cls.counter = 0

    @classmethod
    def tearDownClass(cls) -> None:
        cls.env.close()

    def call(self, method: str, path: str, body: dict | None = None, *, token: str | None = None,
             idempotency: str | None = "auto", headers: dict | None = None) -> tuple[int, dict, dict]:
        from urllib.parse import parse_qs, urlparse

        self.__class__.counter += 1
        parsed = urlparse(path)
        merged = dict(headers or {})
        if token:
            merged["Authorization"] = f"Bearer {token}"
        if method == "POST" and token is not None and idempotency is not None:
            merged["Idempotency-Key"] = idempotency if idempotency != "auto" else f"key-{self.counter}"
        request = ApiRequest(
            method=method, path=parsed.path, query=parse_qs(parsed.query),
            headers={key.lower(): value for key, value in merged.items()},
            body=json.dumps(body).encode("utf-8") if body is not None else b"",
            ip="127.0.0.1",
        )
        response = self.app.handle(request)
        payload = json.loads(response.body.decode("utf-8")) if response.body else {}
        return response.status, payload, dict(response.headers)

    def login(self, username: str = "analyst", password: str = ANALYST_PASSWORD, code: str | None = None) -> str:
        status, payload, _ = self.call("POST", "/api/v1/auth/login",
                                       {"username": username, "password": password, "totp_code": code}, token=None)
        self.assertEqual(status, 200, payload)
        return payload["token"]

    def test_health_is_public(self) -> None:
        status, payload, headers = self.call("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("X-Correlation-ID", headers)

    def test_requires_authentication(self) -> None:
        status, payload, _ = self.call("GET", "/api/v1/instruments")
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "UNAUTHENTICATED")

    def test_login_rejects_bad_password(self) -> None:
        status, payload, _ = self.call("POST", "/api/v1/auth/login",
                                       {"username": "analyst", "password": "nope"}, token=None)
        self.assertEqual(status, 401)

    def test_instruments_and_meta(self) -> None:
        token = self.login()
        status, payload, _ = self.call("GET", "/api/v1/instruments", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(any(item["instrument_id"] == "EURUSD" for item in payload["items"]))
        status, meta, _ = self.call("GET", "/api/v1/meta", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(meta["phase"], "READ_ONLY")
        self.assertFalse(meta["execution_enabled"])

    def test_analysis_requires_idempotency_key(self) -> None:
        token = self.login()
        status, payload, _ = self.call("POST", "/api/v1/analysis-runs",
                                       {"instrument_id": "EURUSD", "timeframe": "H1"}, token=token, idempotency=None)
        self.assertEqual(status, 400)
        self.assertIn("Idempotency", payload["error"]["message"])

    def test_analysis_and_idempotent_replay(self) -> None:
        token = self.login()
        body = {"instrument_id": "EURUSD", "timeframe": "H1", "as_of": self.env.as_of.isoformat()}
        status, first, _ = self.call("POST", "/api/v1/analysis-runs", body, token=token, idempotency="analysis-1")
        self.assertEqual(status, 200, first)
        self.assertIn("run", first)
        status, second, _ = self.call("POST", "/api/v1/analysis-runs", body, token=token, idempotency="analysis-1")
        self.assertEqual(status, 200)
        self.assertEqual(first["run"]["run_id"], second["run"]["run_id"])
        status, listing, _ = self.call("GET", "/api/v1/analysis-runs", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["items"]), 1)

    def test_rbac_denies_audit_to_analyst(self) -> None:
        token = self.login()
        status, payload, _ = self.call("GET", "/api/v1/audit-events", token=token)
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "FORBIDDEN")

    def test_admin_mfa_and_audit_access(self) -> None:
        user = self.env.platform.users.get_by_username("admin")
        secret = self.env.platform.identity.totp_secret(user)
        status, payload, _ = self.call(
            "POST", "/api/v1/auth/login",
            {"username": "admin", "password": ADMIN_PASSWORD,
             "totp_code": totp(secret, at=self.env.clock().timestamp())},
            token=None,
        )
        self.assertEqual(status, 200, payload)
        token = payload["token"]
        status, audit, _ = self.call("GET", "/api/v1/audit-events", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(audit["verification"]["valid"])

    def test_killswitch_requires_permission(self) -> None:
        token = self.login()
        status, payload, _ = self.call("POST", "/api/v1/killswitch",
                                       {"active": True, "reason": "test"}, token=token)
        self.assertEqual(status, 403)

    def test_demo_login_and_totp_helpers(self) -> None:
        status, payload, _ = self.call("POST", "/api/v1/auth/demo-login", {"role": "ANALYST"}, token=None)
        self.assertEqual(status, 200, payload)
        token = payload["token"]
        status, me, _ = self.call("GET", "/api/v1/auth/me", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(me["user"]["role"], "ANALYST")

        status, totp_payload, _ = self.call("GET", "/api/v1/auth/demo-totp?username=admin", token=None)
        self.assertEqual(status, 200, totp_payload)
        self.assertEqual(len(totp_payload["code"]), 6)
        self.assertGreaterEqual(totp_payload["expires_in"], 1)

    def test_demo_login_rejects_admin_role(self) -> None:
        status, payload, _ = self.call("POST", "/api/v1/auth/demo-login", {"role": "ADMIN"}, token=None)
        self.assertEqual(status, 401)
        self.assertIn("MFA", payload["error"]["message"])

    def test_unknown_route(self) -> None:
        token = self.login()
        status, payload, _ = self.call("GET", "/api/v1/nope", token=token)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")

    def test_scenario_flow(self) -> None:
        token = self.login()
        body = {"instrument_id": "EURUSD", "timeframe": "H1", "as_of": self.env.as_of.isoformat()}
        status, analysis, _ = self.call("POST", "/api/v1/analysis-runs", body, token=token, idempotency="flow-1")
        self.assertEqual(status, 200)
        scenario = analysis.get("scenario")
        if scenario is None:
            from fxars.domain.enums import DecisionAction, Direction
            from fxars.domain.models import Decision

            outcome = self.env.platform.analysis_engine.analyze(
                instrument=self.env.instrument, timeframe="H1", candles=self.env.candles,
                as_of=self.env.as_of, run_id="ar_api_flow",
            )
            decision = Decision(
                action=DecisionAction.LONG, direction=Direction.LONG, score=0.5, confidence_raw=0.5,
                family_scores={"STRUCTURE": 0.5}, conflicts=(), coverage=0.5, stability=1.0,
                reasons=("api-test",), evidence_ids=("ev_api",), strength=0.6,
            )
            built = self.env.platform.scenario_builder.build(
                outcome, decision, run_id="ar_api_flow", rules_version="v1",
            )
            self.assertIsNotNone(built.scenario)
            self.env.platform.scenarios.save(built.scenario)
            scenario = built.scenario.to_dict()
        status, detail, _ = self.call("GET", f"/api/v1/scenarios/{scenario['scenario_id']}", token=token)
        self.assertEqual(status, 200)
        self.assertIn("transitions", detail)
        status, evaluated, _ = self.call("POST", f"/api/v1/scenarios/{scenario['scenario_id']}/evaluate",
                                         {}, token=token, idempotency="eval-1")
        self.assertEqual(status, 200)
        self.assertIn("scenario", evaluated)
        status, risk, _ = self.call("POST", "/api/v1/risk/evaluate",
                                    {"scenario_id": scenario["scenario_id"],
                                     "account": {"equity": "10000", "balance": "10000", "free_margin": "10000",
                                                 "taken_at": self.env.clock().isoformat(), "currency": "USD",
                                                 "leverage": "100", "open_positions": 0, "positions": []}},
                                    token=token, idempotency="risk-1")
        self.assertEqual(status, 200, risk)
        self.assertIn("decision", risk)


class DemoDisabledTests(unittest.TestCase):
    def test_demo_endpoints_disabled_outside_dev(self) -> None:
        env = make_env(bars=120, users=True, environment="prod")
        try:
            app = ApiApp(env.platform)
            request = ApiRequest(
                method="POST", path="/api/v1/auth/demo-login", query={},
                headers={"content-type": "application/json"},
                body=b'{"role": "ANALYST"}', ip="127.0.0.1",
            )
            response = app.handle(request)
            self.assertEqual(response.status, 401)
            self.assertIn("development", json.loads(response.body.decode())["error"]["message"])
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
