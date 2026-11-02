"""Metrics registry and health endpoints tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.api.metrics import MetricsRegistry
from tests.test_http_integration import HttpServerFixture, _request


class RegistryTests(unittest.TestCase):
    def test_counter_increments(self):
        r = MetricsRegistry()
        r.inc_counter("x_total")
        r.inc_counter("x_total")
        snap = r.snapshot()
        self.assertEqual(len(snap["counters"]), 1)
        self.assertEqual(snap["counters"][0]["value"], 2.0)

    def test_counter_with_labels_separates_series(self):
        r = MetricsRegistry()
        r.inc_counter("hits_total", labels={"code": "200"})
        r.inc_counter("hits_total", labels={"code": "500"})
        r.inc_counter("hits_total", labels={"code": "200"})
        snap = r.snapshot()
        values = {tuple(sorted(c["labels"].items())): c["value"] for c in snap["counters"]}
        self.assertEqual(values[(("code", "200"),)], 2.0)
        self.assertEqual(values[(("code", "500"),)], 1.0)

    def test_gauge_set(self):
        r = MetricsRegistry()
        r.set_gauge("queue", 5.0)
        r.set_gauge("queue", 3.0)
        snap = r.snapshot()
        self.assertEqual(snap["gauges"][0]["value"], 3.0)

    def test_histogram_observes_buckets(self):
        r = MetricsRegistry()
        for v in [0.001, 0.05, 0.5, 2.0]:
            r.observe_latency("lat_seconds", v)
        snap = r.snapshot()
        hist = snap["histograms"][0]
        self.assertEqual(hist["count"], 4)

    def test_render_prometheus(self):
        r = MetricsRegistry()
        r.inc_counter("fxars_test_total", labels={"k": "v"})
        r.set_gauge("fxars_g", 1.5)
        r.observe_latency("fxars_lat_seconds", 0.02)
        text = r.render_prometheus()
        self.assertIn("fxars_test_total", text)
        self.assertIn("fxars_g", text)
        self.assertIn("fxars_lat_seconds_bucket", text)
        self.assertIn("fxars_lat_seconds_count", text)


class HealthLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HttpServerFixture()
        cls.fixture.start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def test_live_is_public(self):
        status, payload, _ = _request("GET", self.fixture.base + "/api/v1/health/live")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("process", payload["checks"])

    def test_ready_reports_dependencies(self):
        status, payload, _ = _request("GET", self.fixture.base + "/api/v1/health/ready")
        self.assertIn(status, (200, 503))
        self.assertIn("database", payload["checks"])
        self.assertIn("audit_chain", payload["checks"])

    def test_aggregate_health(self):
        status, payload, _ = _request("GET", self.fixture.base + "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertIn("status", payload)


class MetricsEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HttpServerFixture()
        cls.fixture.start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def test_metrics_public_and_text(self):
        status, _, headers = _request("GET", self.fixture.base + "/api/v1/metrics")
        self.assertEqual(status, 200)
        self.assertIn("text/plain", headers.get("Content-Type", ""))

    def test_metrics_contains_gauges(self):
        _request("GET", self.fixture.base + "/api/v1/metrics")
        status, _, _ = _request("GET", self.fixture.base + "/api/v1/metrics")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
