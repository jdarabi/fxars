"""Metrics dashboard tests (P5-4)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.api.metrics import MetricsRegistry
from fxars.api.metrics_dashboard import render_metrics_dashboard

from tests.test_http_integration import HttpServerFixture, _request


class RenderTests(unittest.TestCase):
    def test_empty_snapshot(self):
        r = MetricsRegistry()
        html = render_metrics_dashboard(r.snapshot())
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Metrics Dashboard", html)
        self.assertIn("هیچ شمارنده‌ای ثبت نشده", html)

    def test_with_counters_and_gauges(self):
        r = MetricsRegistry()
        r.inc_counter("fxars_test_total", labels={"k": "v"})
        r.set_gauge("fxars_g", 1.5)
        html = render_metrics_dashboard(r.snapshot(), prometheus_text="fxars_test_total 1.0")
        self.assertIn("fxars_test_total", html)
        self.assertIn("fxars_g", html)

    def test_with_histogram(self):
        r = MetricsRegistry()
        for v in (0.01, 0.05, 0.5):
            r.observe_latency("fxars_lat_seconds", v)
        html = render_metrics_dashboard(r.snapshot())
        self.assertIn("fxars_lat_seconds", html)
        self.assertIn("count:", html)

    def test_escaping(self):
        r = MetricsRegistry()
        r.inc_counter("<script>alert(1)</script>")
        html = render_metrics_dashboard(r.snapshot())
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HttpServerFixture()
        cls.fixture.start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def test_dashboard_public_and_html(self):
        status, _, headers = _request("GET", self.fixture.base + "/metrics-dashboard")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))

    def test_dashboard_contains_metrics(self):
        import urllib.request
        with urllib.request.urlopen(self.fixture.base + "/metrics-dashboard", timeout=5) as resp:
            body = resp.read().decode("utf-8")
            self.assertIn("Metrics Dashboard", body)
            self.assertIn("Uptime", body)


if __name__ == "__main__":
    unittest.main()
