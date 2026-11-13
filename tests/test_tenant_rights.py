"""آزمون حقوق داده و ممیزی امنیت (دروازه فاز ۷)."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

from fxars.api.server import ApiApp, ApiRequest
from fxars.domain.enums import Role
from fxars.platform import Platform
from fxars.storage.db import Database
from fxars.tenancy.audit_check import run_security_audit

from tests.helpers import ANALYST_PASSWORD, Clock, make_env

BETA_PASSWORD = "BetaPass123!"


class DataRightsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = make_env(bars=600, users=True)
        cls.platform = cls.env.platform
        cls.app = ApiApp(cls.platform)
        from fxars.domain.models import Tenant

        cls.platform.tenants.save(
            Tenant(tenant_id="beta", name="Beta", active=True, created_at=cls.platform.clock(), plan="basic")
        )
        cls.platform.identity.create_user("beta_analyst", Role.ANALYST, BETA_PASSWORD, tenant_id="beta")
        admin, _ = cls.platform.identity.create_user(
            "rights_admin", Role.ADMIN, "RightsAdminPass123!", totp_enabled=True,
        )
        cls.admin_token = cls.platform.identity.start_session(admin).token
        cls.counter = 0

    @classmethod
    def tearDownClass(cls) -> None:
        cls.env.close()

    def call(self, method: str, path: str, *, token: str | None = None, body: dict | None = None,
             idempotency: bool = True) -> tuple[int, dict]:
        type(self).counter += 1
        parsed = urlparse(path)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if method == "POST" and token is not None and idempotency:
            headers["Idempotency-Key"] = f"rights-{self.counter}"
        request = ApiRequest(
            method=method, path=parsed.path, query=parse_qs(parsed.query),
            headers={key.lower(): value for key, value in headers.items()},
            body=json.dumps(body).encode("utf-8") if body is not None else b"",
            ip="127.0.0.1",
        )
        response = self.app.handle(request)
        return response.status, json.loads(response.body.decode("utf-8")) if response.body else {}

    def login(self, username: str, password: str) -> str:
        status, payload = self.call(
            "POST", "/api/v1/auth/login", body={"username": username, "password": password},
        )
        self.assertEqual(status, 200, payload)
        return payload["token"]

    def test_export_is_sanitized_and_tenant_scoped(self) -> None:
        token = self.login("analyst", ANALYST_PASSWORD)
        status, payload = self.call("GET", "/api/v1/tenant/export?limit=50", token=token)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["tenant_id"], "default")
        self.assertGreaterEqual(payload["counts"]["users"], 3)
        for user in payload["users"]:
            self.assertEqual(
                set(user),
                {"user_id", "username", "role", "active", "created_at", "tenant_id"},
            )
            self.assertEqual(user["tenant_id"], "default")
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for forbidden in ("password", "totp", "secret", "token"):
            self.assertNotIn(forbidden, serialized)

    def test_retention_report_exposes_policy_and_counts(self) -> None:
        token = self.login("analyst", ANALYST_PASSWORD)
        status, payload = self.call("GET", "/api/v1/tenant/retention", token=token)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["tenant_id"], "default")
        self.assertIn("tenant_data", payload["policy"])
        self.assertEqual(set(payload["counts"]),
                         {"users", "analysis_runs", "scenarios", "risk_decisions", "order_intents"})

    def test_admin_cross_tenant_export_is_isolated(self) -> None:
        status, payload = self.call("GET", "/api/v1/tenants/beta/export", token=self.admin_token)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["tenant_id"], "beta")
        self.assertEqual([user["username"] for user in payload["users"]], ["beta_analyst"])
        self.assertEqual(payload["counts"]["analysis_runs"], 0)

    def test_analyst_cannot_export_other_tenant(self) -> None:
        token = self.login("analyst", ANALYST_PASSWORD)
        status, payload = self.call("GET", "/api/v1/tenants/beta/export", token=token)
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload["error"]["code"], "FORBIDDEN")

    def test_unknown_tenant_export_returns_404(self) -> None:
        status, payload = self.call("GET", "/api/v1/tenants/ghost/export", token=self.admin_token)
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")

    def test_inactive_tenant_rights_blocked(self) -> None:

        beta = self.platform.tenants.get("beta")
        self.platform.tenants.save(replace(beta, active=False))
        try:
            status, payload = self.call("GET", "/api/v1/tenants/beta/retention", token=self.admin_token)
            self.assertEqual(status, 403, payload)
            self.assertEqual(payload["error"]["code"], "TENANT_INACTIVE")
        finally:
            self.platform.tenants.save(beta)

    def test_export_limit_validation(self) -> None:
        status, payload = self.call("GET", "/api/v1/tenant/export?limit=abc", token=self.admin_token)
        self.assertEqual(status, 400, payload)
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")


class SecurityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = make_env(bars=200, users=True)
        cls.platform = cls.env.platform

    @classmethod
    def tearDownClass(cls) -> None:
        cls.env.close()

    def test_dev_audit_reports_no_failures(self) -> None:
        result = run_security_audit(self.platform)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["failed"], 0)
        ids = {check["id"] for check in result["checks"]}
        self.assertLessEqual(
            {"mfa_roles", "session_ttl", "rate_limit", "secret_key", "password_hashing",
             "tenant_columns", "audit_chain", "audit_coverage", "audit_no_secrets", "data_rights"},
            ids,
        )
        by_id = {check["id"]: check for check in result["checks"]}
        self.assertEqual(by_id["secret_key"]["status"], "warn")
        self.assertEqual(by_id["audit_chain"]["status"], "pass")
        self.assertEqual(by_id["tenant_columns"]["status"], "pass")
        self.assertNotIn("dev-insecure", json.dumps(result, ensure_ascii=False))

    def test_prod_audit_fails_on_default_secret(self) -> None:
        env = make_env(bars=200, environment="prod")
        try:
            result = run_security_audit(env.platform)
            self.assertFalse(result["ok"])
            by_id = {check["id"]: check for check in result["checks"]}
            self.assertEqual(by_id["secret_key"]["status"], "fail")
        finally:
            env.close()

    def test_audit_detects_tampered_chain(self) -> None:
        platform = Platform(
            replace(self.platform.settings, db_path=":memory:"),
            db=Database(":memory:"),
            clock=Clock(self.platform.clock()),
            sync_phase=False,
        )
        try:
            platform.bootstrap(create_users=False)
            platform.audit.append("TEST_EVENT", "test", "1", actor="tester", payload={"ok": True})
            platform.db.execute("DROP TRIGGER audit_no_update")
            platform.db.execute(
                "UPDATE audit_events SET entry_hash = ? WHERE seq = (SELECT MAX(seq) FROM audit_events)",
                ("f" * 64,),
            )
            result = run_security_audit(platform)
            by_id = {check["id"]: check for check in result["checks"]}
            self.assertFalse(result["ok"])
            self.assertEqual(by_id["audit_chain"]["status"], "fail")
        finally:
            platform.close()


if __name__ == "__main__":
    unittest.main()
