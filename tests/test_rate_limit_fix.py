"""Regression tests for FIX-08-RATE-LIMIT.

اثبات می‌کند که:
  1. توکن‌های جعلی مختلف از یک IP در یک Bucket مشترک محاسبه می‌شوند.
  2. بعد از احراز هویت، Bucket user_id هم اعمال می‌شود.
  3. /debug/rate-status در dev از localhost پاسخ می‌دهد.
  4. _rate_key حذف شده است.
"""
from __future__ import annotations

import json
import unittest

from fxars.api.server import ApiApp, ApiRequest
from fxars.domain.enums import Role

from tests.helpers import make_env


def _req(method, path, *, headers=None, body=None, ip="9.9.9.9"):
    return ApiRequest(
        method=method,
        path=path,
        query={},
        headers={k.lower(): v for k, v in (headers or {}).items()},
        body=json.dumps(body).encode("utf-8") if body else b"",
        ip=ip,
    )


class RateLimitIPBucketTests(unittest.TestCase):
    """باگ اصلی: توکن جعلی مختلف از یک IP نباید Bucket جدا بسازد."""

    def setUp(self):
        self.env = make_env(bars=120, users=False)
        self.app = ApiApp(self.env.platform)
        self.app.limiter.limit = 3

    def tearDown(self):
        self.env.close()

    def test_fake_tokens_share_ip_bucket(self):
        codes = []
        for i in range(4):
            r = self.app.handle(_req(
                "GET", "/api/v1/instruments",
                headers={"authorization": f"Bearer fake-{i}"},
                ip="9.9.9.9",
            ))
            codes.append(r.status)
        self.assertEqual(codes, [401, 401, 401, 429])

    def test_other_ip_unaffected(self):
        for i in range(3):
            self.app.handle(_req(
                "GET", "/api/v1/instruments",
                headers={"authorization": f"Bearer fake-{i}"},
                ip="9.9.9.9",
            ))
        r = self.app.handle(_req(
            "GET", "/api/v1/instruments",
            headers={"authorization": "Bearer fake-x"},
            ip="8.8.8.8",
        ))
        self.assertEqual(r.status, 401)


class RateLimitUserBucketTests(unittest.TestCase):
    """بعد از auth، Bucket user_id هم اعمال می‌شود."""

    def setUp(self):
        self.env = make_env(bars=120, users=False)
        self.env.platform.identity.create_user("rltest", Role.ANALYST, "RlTestPass123!")
        self.app = ApiApp(self.env.platform)
        self.app.limiter.limit = 5
        self.token = self.env.platform.identity.login("rltest", "RlTestPass123!").token

    def tearDown(self):
        self.env.close()

    def test_user_bucket_after_auth(self):
        for _ in range(5):
            r = self.app.handle(_req(
                "GET", "/api/v1/instruments",
                headers={"authorization": f"Bearer {self.token}"},
                ip="9.9.9.9",
            ))
            self.assertEqual(r.status, 200)
        r = self.app.handle(_req(
            "GET", "/api/v1/instruments",
            headers={"authorization": f"Bearer {self.token}"},
            ip="9.9.9.9",
        ))
        self.assertEqual(r.status, 429)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.env = make_env(bars=120, users=False)
        self.app = ApiApp(self.env.platform)

    def tearDown(self):
        self.env.close()

    def test_hits_for(self):
        self.app.limiter.allow("ip:1.2.3.4")
        self.app.limiter.allow("ip:1.2.3.4")
        self.assertEqual(self.app.limiter.hits_for("ip:1.2.3.4"), 2)
        self.assertEqual(self.app.limiter.hits_for("ip:unknown"), 0)

    def test_snapshot(self):
        self.app.limiter.allow("ip:a")
        self.app.limiter.allow("ip:a")
        self.app.limiter.allow("user:b")
        snap = self.app.limiter.snapshot()
        self.assertEqual(snap.get("ip:a"), 2)
        self.assertEqual(snap.get("user:b"), 1)

    def test_debug_endpoint_localhost(self):
        r = self.app.handle(_req("GET", "/api/v1/debug/rate-status", ip="127.0.0.1"))
        self.assertEqual(r.status, 200)
        payload = json.loads(r.body.decode())
        self.assertIn("limit_per_minute", payload)
        self.assertIn("buckets", payload)


class RateKeyRemovedTests(unittest.TestCase):
    def test_rate_key_method_is_gone(self):
        from fxars.api.server import ApiApp
        self.assertFalse(
            hasattr(ApiApp, "_rate_key"),
            "_rate_key must be removed after FIX-08",
        )


if __name__ == "__main__":
    unittest.main()
