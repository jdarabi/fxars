"""آزمون هارنس Forward Test (فاز ۶)."""

from __future__ import annotations

import unittest

from fxars.live.forward_test import ForwardTestHarness

from tests.helpers import make_env


class ForwardTestHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=400)

    def tearDown(self) -> None:
        self.env.close()

    def test_event_time_replay_is_lookahead_safe(self) -> None:
        report = ForwardTestHarness(
            self.env.platform, "EURUSD", "H1", warmup=150, step_size=50,
        ).run(as_of=self.env.as_of)
        self.assertEqual(report.verdict, "PASS")
        self.assertEqual(len(report.steps), 5)
        self.assertEqual(report.lookahead_violations, [])
        self.assertEqual(report.errors, [])
        payload = report.to_dict()
        self.assertEqual(
            payload["long"] + payload["short"] + payload["no_trade"],
            payload["candles_tested"],
        )

    def test_insufficient_data(self) -> None:
        report = ForwardTestHarness(
            self.env.platform, "EURUSD", "H1", warmup=1000,
        ).run(as_of=self.env.as_of)
        self.assertEqual(report.verdict, "INSUFFICIENT_DATA")
        self.assertEqual(report.steps, [])

    def test_max_steps_caps_work(self) -> None:
        report = ForwardTestHarness(
            self.env.platform, "EURUSD", "H1", warmup=150, step_size=10,
        ).run(as_of=self.env.as_of, max_steps=3)
        self.assertEqual(len(report.steps), 3)
        self.assertEqual(report.verdict, "PASS")

    def test_invalid_step_size(self) -> None:
        with self.assertRaises(ValueError):
            ForwardTestHarness(self.env.platform, "EURUSD", "H1", step_size=0)


if __name__ == "__main__":
    unittest.main()
