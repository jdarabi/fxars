"""آزمون قابلیت‌های اطلاعاتی تصمیم و endpointهای تکمیلی API."""

from __future__ import annotations

import json
import unittest
from datetime import timedelta

from fxars.api.server import ApiApp, ApiRequest
from fxars.core.errors import NotFoundError, ValidationError
from fxars.domain.enums import BacktestSegment, Direction, ScenarioStatus
from fxars.domain.models import BacktestRun, PriceZone, Scenario

from tests.helpers import ANALYST_PASSWORD, make_env


def scenario(env, *, scenario_id: str = "sc_info", direction: Direction = Direction.LONG,
             status: ScenarioStatus = ScenarioStatus.WATCH,
             created_at=None, entry: str = "1.0870", stop: str = "1.0800",
             target: str = "1.0975", strength: float = 0.6) -> Scenario:
    return Scenario(
        scenario_id=scenario_id, instrument_id="EURUSD", timeframe="H1", direction=direction,
        status=status,
        entry_condition={"type": "price_cross_above", "level": entry, "timeframe": "H1",
                         "require_closed_candle": True},
        entry_zone=PriceZone("1.0860", "1.0880"),
        invalidation_condition={"type": "close_below", "level": stop, "timeframe": "H1"},
        stop_logic={"type": "structure_low", "level": stop, "buffer_pips": 5},
        target_logic=({"type": "rr_multiple", "value": 1.5, "price": target},),
        expiry_at=env.as_of + timedelta(hours=8),
        evidence_ids=("ev_1",), analysis_run_id="ar_test", decision_explanation="test",
        created_at=created_at or env.as_of, updated_at=env.as_of,
        rules_version="v1", config_hash="hash", strength=strength,
    )


class IntelligenceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)
        self.service = self.env.platform.intelligence

    def tearDown(self) -> None:
        self.env.close()

    def test_journal_roundtrip_and_validation(self) -> None:
        entry = self.service.journal_add(
            kind="hypothesis", body="اگر شکست سطح تثبیت شود، سناریوی خرید معتبر است.",
            actor="analyst", scenario_id="sc_info", payload={"confidence": 0.6},
        )
        self.assertEqual(entry["kind"], "HYPOTHESIS")
        items = self.service.journal_list(scenario_id="sc_info")
        self.assertEqual(len(items), 1)
        with self.assertRaises(ValidationError):
            self.service.journal_add(kind="UNKNOWN", body="x", actor="analyst")
        with self.assertRaises(ValidationError):
            self.service.journal_add(kind="NOTE", body=" ", actor="analyst")

    def test_heatmap_detects_crowding(self) -> None:
        self.env.platform.scenarios.save(scenario(self.env, scenario_id="sc_long"))
        self.env.platform.scenarios.save(scenario(
            self.env, scenario_id="sc_short", direction=Direction.SHORT,
            entry="1.0800", stop="1.0870", target="1.0700",
        ))
        result = self.service.heatmap()
        self.assertEqual(result["total"], 2)
        row = result["rows"][0]
        self.assertEqual(row["crowding"], "CROWDED")
        self.assertEqual(row["LONG"], 1)
        self.assertEqual(row["SHORT"], 1)

    def test_premortem_structure(self) -> None:
        run = self.env.analyze().run
        result = self.service.premortem(run.run_id)
        self.assertEqual(result["run_id"], run.run_id)
        self.assertIsInstance(result["findings"], list)
        for finding in result["findings"]:
            self.assertIn(finding["severity"], {"LOW", "MEDIUM", "HIGH"})
            self.assertTrue(finding["detail"])

    def test_counterfactual_variants(self) -> None:
        self.env.platform.scenarios.save(scenario(
            self.env, created_at=self.env.as_of - timedelta(hours=12),
        ))
        result = self.service.counterfactual("sc_info", max_bars=12)
        self.assertTrue(result["ok"])
        labels = [item["label"] for item in result["variants"]]
        self.assertEqual(labels, ["SCENARIO", "REVERSED", "NO_TRADE"])
        self.assertGreater(result["samples"], 0)

    def test_counterfactual_without_horizon(self) -> None:
        self.env.platform.scenarios.save(scenario(self.env))
        result = self.service.counterfactual("sc_info")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "NO_FORWARD_CANDLES")

    def test_challenge_roundtrip(self) -> None:
        self.env.platform.scenarios.save(scenario(self.env))
        challenge = self.service.challenge_add(
            "sc_info", thesis="شکست کاذب محتمل است.", actor="analyst",
            evidence=["BOJ", "spread"], severity="high",
        )
        self.assertEqual(challenge["severity"], "HIGH")
        self.assertEqual(len(self.service.challenge_list("sc_info")), 1)
        with self.assertRaises(ValidationError):
            self.service.challenge_add("sc_info", thesis=" ", actor="analyst")
        with self.assertRaises(ValidationError):
            self.service.challenge_add("sc_info", thesis="x", actor="analyst", severity="EXTREME")
        with self.assertRaises(NotFoundError):
            self.service.challenge_add("sc_missing", thesis="x", actor="analyst")


class SupplementApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = make_env(bars=600, users=True)
        cls.app = ApiApp(cls.env.platform)
        cls.counter = 0
        cls.analysis = cls.env.analyze()
        cls.env.platform.scenarios.save(scenario(cls.env, scenario_id="sc_api"))
        cls.backtest = BacktestRun(
            run_id="bt_api", instrument_id="EURUSD", timeframe="H1", config={},
            config_hash="hash", data_snapshot_id="snap", code_version="1.8.0",
            segment=BacktestSegment.LOCKED_TEST,
            started_at=cls.env.as_of - timedelta(days=10), finished_at=cls.env.as_of,
            metrics={
                "trade_count": 300, "profit_factor": 1.4, "max_drawdown_pct": 0.08,
                "sharpe": 1.1, "calmar": 0.9, "costs": {"total": 120.0},
                "calibration": {"ece": 0.03}, "locked_test": True, "walkforward": True,
            },
            trades=(), equity_curve=(), seed=7,
        )
        cls.env.platform.backtests.save(cls.backtest)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.env.close()

    def call(self, method: str, path: str, body: dict | None = None, *,
             token: str | None = None) -> tuple[int, dict]:
        from urllib.parse import parse_qs, urlparse

        type(self).counter += 1
        parsed = urlparse(path)
        headers = {"content-type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if method == "POST" and token is not None:
            headers["Idempotency-Key"] = f"intel-{self.counter}"
        request = ApiRequest(
            method=method, path=parsed.path, query=parse_qs(parsed.query),
            headers={key.lower(): value for key, value in headers.items()},
            body=json.dumps(body).encode("utf-8") if body is not None else b"",
            ip="127.0.0.1",
        )
        response = self.app.handle(request)
        payload = json.loads(response.body.decode("utf-8")) if response.body else {}
        return response.status, payload

    def login(self, username: str = "analyst", password: str = ANALYST_PASSWORD) -> str:
        status, payload = self.call(
            "POST", "/api/v1/auth/login", {"username": username, "password": password},
        )
        self.assertEqual(status, 200, payload)
        return payload["token"]

    def login_admin(self) -> str:
        from fxars.identity.totp import totp

        from tests.helpers import ADMIN_PASSWORD

        user = self.env.platform.users.get_by_username("admin")
        secret = self.env.platform.identity.totp_secret(user)
        status, payload = self.call(
            "POST", "/api/v1/auth/login",
            {"username": "admin", "password": ADMIN_PASSWORD,
             "totp_code": totp(secret, at=self.env.clock().timestamp())},
        )
        self.assertEqual(status, 200, payload)
        return payload["token"]

    def test_journal_and_heatmap(self) -> None:
        token = self.login()
        status, payload = self.call(
            "POST", "/api/v1/intelligence/journal",
            {"kind": "NOTE", "body": "بررسی نهایی قبل از جلسه.", "scenario_id": "sc_api"},
            token=token,
        )
        self.assertEqual(status, 201, payload)
        status, payload = self.call("GET", "/api/v1/intelligence/journal?scenario_id=sc_api", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        status, payload = self.call("GET", "/api/v1/intelligence/heatmap", token=token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(payload["total"], 1)

    def test_premortem_provenance_and_challenge(self) -> None:
        token = self.login()
        run_id = self.analysis.run.run_id
        status, payload = self.call("GET", f"/api/v1/intelligence/premortem/{run_id}", token=token)
        self.assertEqual(status, 200, payload)
        self.assertIn("findings", payload)
        admin = self.login_admin()
        status, payload = self.call("GET", f"/api/v1/governance/provenance/{run_id}", token=admin)
        self.assertEqual(status, 200, payload)
        self.assertGreaterEqual(payload["count"], 1)
        self.assertTrue(payload["chain"]["valid"])
        status, payload = self.call(
            "POST", "/api/v1/intelligence/challenges/sc_api",
            {"thesis": "نقد مستقل", "severity": "HIGH"}, token=token,
        )
        self.assertEqual(status, 201, payload)
        status, payload = self.call("GET", "/api/v1/intelligence/challenges/sc_api", token=token)
        self.assertEqual(payload["count"], 1)

    def test_counterfactual_endpoint(self) -> None:
        token = self.login()
        status, payload = self.call(
            "GET", "/api/v1/intelligence/counterfactual/sc_api?max_bars=5", token=token,
        )
        self.assertEqual(status, 200)
        self.assertIn("variants", payload)

    def test_risk_lock_endpoint(self) -> None:
        token = self.login()
        status, payload = self.call("GET", "/api/v1/risk/lock", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["risk_lock"]["state"], "NORMAL")
        status, payload = self.call(
            "POST", "/api/v1/risk/lock", {"reason": "بازبینی دستی"}, token=token,
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["risk_lock"]["state"], "MANUAL_REVIEW")
        status, payload = self.call(
            "POST", "/api/v1/risk/lock", {"reason": "آزادسازی", "release": True}, token=token,
        )
        self.assertEqual(payload["risk_lock"]["state"], "NORMAL")

    def test_governance_rbac_and_registries(self) -> None:
        analyst = self.login()
        status, _ = self.call(
            "POST", "/api/v1/governance/policies",
            {"kind": "risk", "values": {"risk_per_trade": 0.005}}, token=analyst,
        )
        self.assertEqual(status, 403)
        manager = self.login_admin()
        status, payload = self.call(
            "POST", "/api/v1/governance/policies",
            {"kind": "risk", "values": {"risk_per_trade": 0.005}, "version": "api-v1"},
            token=manager,
        )
        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["policy"]["status"], "DRAFT")
        status, payload = self.call("GET", "/api/v1/governance/policies?kind=risk", token=manager)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(payload["count"], 1)
        status, payload = self.call(
            "POST", "/api/v1/governance/models",
            {
                "model_id": "reporter", "version": "0.1.0", "tier": 0,
                "purpose": "گزارش", "owner": "research", "training_data": "none",
                "feature_schema": "none", "limitations": ["فقط گزارش"],
            },
            token=manager,
        )
        self.assertEqual(status, 201, payload)
        status, payload = self.call("GET", "/api/v1/governance/models", token=manager)
        self.assertEqual(payload["count"], 1)

    def test_acceptance_endpoint(self) -> None:
        token = self.login()
        status, payload = self.call("GET", "/api/v1/governance/acceptance/bt_api", token=token)
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["passed"], payload["failures"])
        self.assertEqual(payload["anti_patterns"], [])


if __name__ == "__main__":
    unittest.main()
