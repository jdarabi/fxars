"""Security hardening tests.

Covers: RBAC matrix completeness, rate limiting, header injection,
body size limits, CORS preflight, killswitch reason requirement.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.domain.enums import Permission, Role
from fxars.identity.rbac import ROLE_PERMISSIONS, has_permission, permissions_for, require_permission

from tests.helpers import ANALYST_PASSWORD
from tests.test_http_integration import HttpServerFixture, _request


class RbacMatrixTests(unittest.TestCase):
    def test_every_role_has_defined_permissions(self):
        for role in Role:
            self.assertIn(role, ROLE_PERMISSIONS, f"missing role: {role}")

    def test_admin_has_every_permission(self):
        admin_perms = permissions_for(Role.ADMIN)
        for perm in Permission:
            self.assertIn(perm, admin_perms, f"ADMIN missing {perm}")

    def test_analyst_cannot_administer_users(self):
        self.assertFalse(has_permission(Role.ANALYST, Permission.USERS_ADMIN))

    def test_analyst_cannot_read_audit(self):
        self.assertFalse(has_permission(Role.ANALYST, Permission.AUDIT_READ))

    def test_auditor_cannot_execute_orders(self):
        self.assertFalse(has_permission(Role.AUDITOR, Permission.EXECUTION_ORDER))

    def test_auditor_can_read_audit(self):
        self.assertTrue(has_permission(Role.AUDITOR, Permission.AUDIT_READ))

    def test_risk_manager_can_toggle_killswitch(self):
        self.assertTrue(has_permission(Role.RISK_MANAGER, Permission.KILLSWITCH_TOGGLE))

    def test_operator_can_execute_orders(self):
        self.assertTrue(has_permission(Role.OPERATOR, Permission.EXECUTION_ORDER))

    def test_tenant_user_has_read_only(self):
        perms = permissions_for(Role.TENANT_USER)
        self.assertIn(Permission.DATA_READ, perms)
        self.assertIn(Permission.SCENARIO_READ, perms)
        self.assertNotIn(Permission.RISK_EVALUATE, perms)

    def test_require_permission_raises_on_missing(self):
        from fxars.core.errors import AuthorizationError
        with self.assertRaises(AuthorizationError):
            require_permission(Role.ANALYST, Permission.AUDIT_READ)


class RateLimitTests(unittest.TestCase):
    def test_rate_limiter_rejects_after_limit(self):
        from fxars.api.rate_limit import MemoryRateLimiter as RateLimiter
        limiter = RateLimiter(limit=3, window_seconds=60)
        for _ in range(3):
            self.assertTrue(limiter.allow("k1"))
        self.assertFalse(limiter.allow("k1"))
        # Other key unaffected
        self.assertTrue(limiter.allow("k2"))

    def test_rate_limiter_window_expires(self):
        import time

        from fxars.api.rate_limit import MemoryRateLimiter as RateLimiter
        limiter = RateLimiter(limit=1, window_seconds=0.05)
        self.assertTrue(limiter.allow("k1"))
        self.assertFalse(limiter.allow("k1"))
        time.sleep(0.1)
        self.assertTrue(limiter.allow("k1"))


class BodySizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HttpServerFixture()
        cls.fixture.start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def _token(self) -> str:
        status, payload, _ = _request(
            "POST",
            self.fixture.base + "/api/v1/auth/login",
            body={"username": "analyst", "password": ANALYST_PASSWORD},
        )
        self.assertEqual(status, 200, payload)
        return payload["token"]

    def test_payload_too_large_returns_413(self):
        token = self._token()
        big = "x" * (self.fixture.env.settings.api.max_body_bytes + 1024)
        try:
            status, payload, _ = _request(
                "POST",
                self.fixture.base + "/api/v1/analysis-runs",
                body={"instrument_id": "EURUSD", "timeframe": "H1", "junk": big},
                token=token,
                idempotency_key="big-body-1",
                timeout=20.0,
            )
        except ConnectionAbortedError:
            # Server drained and closed; that's also a valid rejection.
            return
        self.assertIn(status, (400, 413), payload)


class HeaderInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HttpServerFixture()
        cls.fixture.start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def test_invalid_bearer_returns_401(self):
        status, payload, _ = _request(
            "GET",
            self.fixture.base + "/api/v1/instruments",
            token="<script>alert(1)</script>",
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "UNAUTHENTICATED")
        self.assertNotIn("<script>", json.dumps(payload, ensure_ascii=False))


class CorsPreflightTests(unittest.TestCase):
    """FIX-16b-CORS-ISOLATION: هر تست fixture مستقل دارد (setUp/tearDown)."""

    def setUp(self):
        self.fixture = HttpServerFixture()
        self.fixture.start()

    def tearDown(self):
        self.fixture.stop()

    def _options(self, url):
        import urllib.request
        req = urllib.request.Request(url, method="OPTIONS")
        with urllib.request.urlopen(req, timeout=5) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, headers

    def test_options_no_acao_when_cors_empty(self):
        """پیش‌فرض: cors_allow_origin خالی → ACAO نباید ارسال شود (امن)."""
        status, headers = self._options(self.fixture.base + "/api/v1/health")
        self.assertEqual(status, 204)
        self.assertNotIn(
            "access-control-allow-origin", headers,
            "امنیت: ACAO نباید با cors_allow_origin خالی ارسال شود",
        )
        self.assertIn("access-control-allow-headers", headers)
        self.assertIn("access-control-allow-methods", headers)
        self.assertIn("GET", headers["access-control-allow-methods"])

    def test_options_acao_when_cors_configured(self):
        """با cors_allow_origin معتبر → ACAO ارسال شود."""
        from fxars.api.server import ApiApp
        new_settings = self.fixture.env.settings.__class__.from_dict({
            "phase": "READ_ONLY",
            "db_path": ":memory:",
            "environment": "dev",
            "api": {"cors_allow_origin": "https://example.com"},
        })
        self.fixture.env.platform.settings = new_settings
        self.fixture.server.app = ApiApp(self.fixture.env.platform)
        status, headers = self._options(self.fixture.base + "/api/v1/health")
        self.assertEqual(status, 204)
        self.assertEqual(
            headers.get("access-control-allow-origin"),
            "https://example.com",
        )

class KillSwitchSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HttpServerFixture()
        cls.fixture.start()
        # Create an admin with MFA for killswitch testing
        admin, _ = cls.fixture.env.platform.identity.create_user(
            "secadmin", Role.ADMIN, "SecAdminPass12345!", totp_enabled=True,
        )
        cls.admin_user = admin
        cls.totp_secret = cls.fixture.env.platform.identity.totp_secret(admin)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def _admin_token(self) -> str:
        from fxars.identity.totp import totp
        # FIX-P2-3: use the fixture clock (not wall clock) so TOTP matches IdentityService.login
        code = totp(self.totp_secret, at=self.fixture.env.clock().timestamp())
        status, payload, _ = _request(
            "POST",
            self.fixture.base + "/api/v1/auth/login",
            body={"username": "secadmin", "password": "SecAdminPass12345!", "totp_code": code},
        )
        self.assertEqual(status, 200, payload)
        return payload["token"]

    def test_killswitch_requires_reason(self):
        token = self._admin_token()
        status, payload, _ = _request(
            "POST",
            self.fixture.base + "/api/v1/killswitch",
            body={"active": True},  # missing reason
            token=token,
            idempotency_key="ks-no-reason-1",
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

    def test_killswitch_deactivate_round_trip_updates_meta(self):
        token = self._admin_token()
        status, payload, _ = _request(
            "POST",
            self.fixture.base + "/api/v1/killswitch",
            body={"active": True, "reason": "round trip on"},
            token=token,
            idempotency_key="ks-rt-on",
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["killswitch"]["active"])

        status, payload, _ = _request(
            "POST",
            self.fixture.base + "/api/v1/killswitch",
            body={"active": False, "reason": "round trip off"},
            token=token,
            idempotency_key="ks-rt-off",
        )
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["killswitch"]["active"])

        status, meta, _ = _request("GET", self.fixture.base + "/api/v1/meta", token=token)
        self.assertEqual(status, 200, meta)
        self.assertFalse(meta["killswitch"]["active"])

    def test_killswitch_with_reason_succeeds(self):
        token = self._admin_token()
        status, payload, _ = _request(
            "POST",
            self.fixture.base + "/api/v1/killswitch",
            body={"active": True, "reason": "security test"},
            token=token,
            idempotency_key="ks-with-reason-1",
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["killswitch"]["active"])
        # Cleanup
        _request(
            "POST",
            self.fixture.base + "/api/v1/killswitch",
            body={"active": False, "reason": "cleanup"},
            token=token,
            idempotency_key="ks-cleanup-1",
        )


if __name__ == "__main__":
    unittest.main()

# FIX-16-CORS-TEST

# FIX-16b-CORS-ISOLATION
