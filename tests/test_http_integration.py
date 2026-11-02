"""HTTP integration tests against a real FxarsServer.

Covers: BaseHTTPRequestHandler parsing, ThreadingHTTPServer lifecycle,
urllib client behavior, Idempotency-Key, Authorization header, error bodies.
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.api.server import create_server
from fxars.domain.enums import Role
from tests.helpers import ANALYST_PASSWORD, make_env


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HttpServerFixture:
    """Spin up a real FxarsServer on a free port for the test duration."""

    def __init__(self):
        self.env = make_env(bars=200, users=True)
        self.env.platform.identity.create_user("httptest", Role.ANALYST, "HttpPass123!")
        self.port = _free_port()
        self.server = create_server(self.env.platform, host="127.0.0.1", port=self.port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.base = f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.02)
        raise RuntimeError("server did not become ready")

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.env.close()


def _request(
    method: str,
    url: str,
    *,
    body: dict | None = None,
    token: str | None = None,
    idempotency_key: str | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict, dict]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
            response_headers = dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
        response_headers = dict(exc.headers or {})
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"raw": raw.decode("utf-8", errors="replace")}
    return status, payload, response_headers


class HttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HttpServerFixture()
        cls.fixture.start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def _login(self, username: str = "analyst", password: str = ANALYST_PASSWORD) -> str:
        status, payload, _ = _request(
            "POST",
            self.fixture.base + "/api/v1/auth/login",
            body={"username": username, "password": password},
        )
        self.assertEqual(status, 200, payload)
        return payload["token"]

    def test_health_over_http(self):
        status, payload, headers = _request("GET", self.fixture.base + "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("X-Correlation-ID", headers)

    def test_requires_bearer(self):
        status, payload, _ = _request("GET", self.fixture.base + "/api/v1/instruments")
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "UNAUTHENTICATED")

    def test_login_and_me(self):
        token = self._login()
        status, payload, _ = _request(
            "GET",
            self.fixture.base + "/api/v1/auth/me",
            token=token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["user"]["username"], "analyst")

    def test_post_requires_idempotency_key(self):
        token = self._login()
        status, payload, _ = _request(
            "POST",
            self.fixture.base + "/api/v1/analysis-runs",
            body={"instrument_id": "EURUSD", "timeframe": "H1", "as_of": self.fixture.env.as_of.isoformat()},
            token=token,
        )
        self.assertEqual(status, 400)
        self.assertIn("Idempotency", payload["error"]["message"])

    def test_analysis_idempotent_over_http(self):
        token = self._login()
        body = {
            "instrument_id": "EURUSD",
            "timeframe": "H1",
            "as_of": self.fixture.env.as_of.isoformat(),
        }
        status1, payload1, _ = _request(
            "POST",
            self.fixture.base + "/api/v1/analysis-runs",
            body=body,
            token=token,
            idempotency_key="http-replay-1",
        )
        self.assertEqual(status1, 200, payload1)
        run_id_1 = payload1["run"]["run_id"]

        status2, payload2, _ = _request(
            "POST",
            self.fixture.base + "/api/v1/analysis-runs",
            body=body,
            token=token,
            idempotency_key="http-replay-1",
        )
        self.assertEqual(status2, 200)
        self.assertEqual(payload2["run"]["run_id"], run_id_1)

    def test_rbac_over_http(self):
        token = self._login()
        status, payload, _ = _request(
            "GET",
            self.fixture.base + "/api/v1/audit-events",
            token=token,
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "FORBIDDEN")

    def test_candles_order_desc_default(self):
        token = self._login()
        status, payload, _ = _request(
            "GET",
            self.fixture.base + "/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=3",
            token=token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["order"], "desc")
        self.assertLessEqual(len(payload["items"]), 3)

    def test_candles_order_asc(self):
        token = self._login()
        status, payload, _ = _request(
            "GET",
            self.fixture.base + "/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=3&order=asc",
            token=token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["order"], "asc")

    def test_unknown_route_returns_404_json(self):
        token = self._login()
        status, payload, _ = _request(
            "GET",
            self.fixture.base + "/api/v1/no-such-thing",
            token=token,
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")

    def test_method_not_allowed(self):
        token = self._login()
        status, payload, _ = _request(
            "DELETE",
            self.fixture.base + "/api/v1/health",
            token=token,
        )
        self.assertIn(status, (404, 405, 501), f"unexpected status for unsupported method: {status}")

    def test_killswitch_requires_permission_over_http(self):
        token = self._login()
        status, payload, _ = _request(
            "POST",
            self.fixture.base + "/api/v1/killswitch",
            body={"active": True, "reason": "http test"},
            token=token,
            idempotency_key="kill-http-1",
        )
        self.assertEqual(status, 403)


class HttpServerShutdownTests(unittest.TestCase):
    def test_server_can_start_and_stop(self):
        fixture = HttpServerFixture()
        try:
            fixture.start()
            status, payload, _ = _request("GET", fixture.base + "/api/v1/health")
            self.assertEqual(status, 200)
        finally:
            fixture.stop()


if __name__ == "__main__":
    unittest.main()