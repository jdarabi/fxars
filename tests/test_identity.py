"""آزمون هویت: رمز، TOTP، RBAC، نشست و محدودیت ورود."""

from __future__ import annotations

import unittest
from datetime import timedelta

from fxars.core.errors import AuthenticationError, RateLimitedError, ValidationError
from fxars.domain.enums import Permission, Role
from fxars.identity.passwords import SecretBox, hash_password, verify_password
from fxars.identity.rbac import has_permission, permissions_for, require_permission
from fxars.identity.totp import hotp, provisioning_uri, totp, verify_totp
from tests.helpers import ADMIN_PASSWORD, ANALYST_PASSWORD, make_env


class PasswordTests(unittest.TestCase):
    def test_hash_and_verify(self) -> None:
        encoded = hash_password("StrongPassword123", iterations=10_000)
        self.assertTrue(verify_password("StrongPassword123", encoded))
        self.assertFalse(verify_password("WrongPassword123", encoded))

    def test_short_password_rejected(self) -> None:
        with self.assertRaises(ValueError):
            hash_password("short")

    def test_secret_box_roundtrip(self) -> None:
        box = SecretBox("key")
        encrypted = box.encrypt("secret-value")
        self.assertNotIn("secret-value", encrypted)
        self.assertEqual(box.decrypt(encrypted), "secret-value")


class TotpTests(unittest.TestCase):
    def test_rfc_vector(self) -> None:
        # RFC 6238، SHA1، T=59
        self.assertEqual(hotp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 1, digits=6), "287082")
        self.assertTrue(verify_totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", "287082", at=59))

    def test_current_code(self) -> None:
        secret = "JBSWY3DPEHPK3PXP"
        code = totp(secret, at=1_700_000_000)
        self.assertTrue(verify_totp(secret, code, at=1_700_000_000))
        self.assertFalse(verify_totp(secret, "000000", at=1_700_000_000))

    def test_provisioning_uri(self) -> None:
        uri = provisioning_uri("JBSWY3DPEHPK3PXP", "admin")
        self.assertTrue(uri.startswith("otpauth://totp/"))
        self.assertIn("secret=JBSWY3DPEHPK3PXP", uri)


class RbacTests(unittest.TestCase):
    def test_permissions(self) -> None:
        self.assertTrue(has_permission(Role.ADMIN, Permission.USERS_ADMIN))
        self.assertTrue(has_permission(Role.ANALYST, Permission.ANALYSIS_RUN))
        self.assertFalse(has_permission(Role.ANALYST, Permission.AUDIT_READ))
        self.assertIn(Permission.KILLSWITCH_TOGGLE, permissions_for(Role.RISK_MANAGER))

    def test_require_permission_raises(self) -> None:
        from fxars.core.errors import AuthorizationError

        require_permission(Role.AUDITOR, Permission.AUDIT_READ)
        with self.assertRaises(AuthorizationError):
            require_permission(Role.AUDITOR, Permission.EXECUTION_ORDER)


class SessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=100, users=True)
        self.identity = self.env.platform.identity

    def tearDown(self) -> None:
        self.env.close()

    def test_login_and_resolve(self) -> None:
        result = self.identity.login("analyst", ANALYST_PASSWORD, ip="127.0.0.1")
        self.assertTrue(result.token)
        resolved = self.identity.resolve_session(result.token)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved[0].username, "analyst")

    def test_wrong_password(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.identity.login("analyst", "wrong-password")

    def test_admin_requires_mfa(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.identity.login("admin", ADMIN_PASSWORD)

    def test_admin_with_totp(self) -> None:
        user = self.env.platform.users.get_by_username("admin")
        secret = self.identity.totp_secret(user)
        code = totp(secret, at=self.env.clock().timestamp())
        result = self.identity.login("admin", ADMIN_PASSWORD, totp_code=code)
        self.assertEqual(result.user.role, Role.ADMIN)

    def test_session_expiry(self) -> None:
        result = self.identity.login("analyst", ANALYST_PASSWORD)
        self.env.clock.advance(60 * 60 * 24)
        self.assertIsNone(self.identity.resolve_session(result.token))

    def test_logout_revokes(self) -> None:
        result = self.identity.login("analyst", ANALYST_PASSWORD)
        self.identity.logout(result.token)
        self.assertIsNone(self.identity.resolve_session(result.token))

    def test_rate_limit_after_failures(self) -> None:
        for _ in range(self.env.settings.security.login_max_attempts):
            with self.assertRaises(AuthenticationError):
                self.identity.login("analyst", "bad-password")
        with self.assertRaises(RateLimitedError):
            self.identity.login("analyst", "bad-password")

    def test_duplicate_username_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.identity.create_user("analyst", Role.ANALYST, "AnotherPass123")


if __name__ == "__main__":
    unittest.main()
