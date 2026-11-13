"""اعمال فاز در زمان اجرا: سوئیچ فاز باید بدون ری‌استارت اثر کند."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fxars.api.server import ApiApp, ApiRequest

from tests.helpers import make_env


class RuntimePhaseApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=120)
        self.platform = self.env.platform
        self._tmp = tempfile.TemporaryDirectory()
        # مسیر فایل فاز را به temp می‌بریم تا config واقعی پروژه دست‌نخورده بماند.
        self.platform.phase_path = Path(self._tmp.name) / "phase.json"

    def tearDown(self) -> None:
        self.platform.close()
        self._tmp.cleanup()

    def test_paper_creates_broker_and_enables_execution(self) -> None:
        outcome = self.platform.apply_phase("PAPER")
        self.assertEqual(outcome["runtime_phase"], "PAPER")
        self.assertTrue(outcome["execution_enabled"])
        self.assertEqual(outcome["broker"], "paper")
        self.assertEqual(self.platform.execution.broker.name, "paper")
        self.assertIs(self.platform.execution.settings, self.platform.settings)
        self.assertIs(self.platform.strategy_execution.settings, self.platform.settings)
        self.assertIs(self.platform.close_reconciliation.broker, self.platform.execution.broker)
        self.assertEqual(self.platform.settings.phase.value, "PAPER")

    def test_back_to_read_only_drops_broker(self) -> None:
        self.platform.apply_phase("PAPER")
        outcome = self.platform.apply_phase("READ_ONLY")
        self.assertEqual(outcome["runtime_phase"], "READ_ONLY")
        self.assertFalse(outcome["execution_enabled"])
        self.assertIsNone(self.platform.execution.broker)
        self.assertIsNone(self.platform.close_reconciliation.broker)

    def test_advisor_maps_to_read_only_at_runtime(self) -> None:
        self.platform.apply_phase("PAPER")
        outcome = self.platform.apply_phase("ADVISOR")
        self.assertEqual(outcome["requested_mode"], "ADVISOR")
        self.assertEqual(outcome["runtime_phase"], "READ_ONLY")
        self.assertIsNone(self.platform.execution.broker)

    def test_automated_limited_respects_enabled_flag(self) -> None:
        outcome = self.platform.apply_phase("AUTOMATED_LIMITED", automated_enabled=False)
        self.assertEqual(outcome["runtime_phase"], "READ_ONLY")
        outcome = self.platform.apply_phase("AUTOMATED_LIMITED", automated_enabled=True)
        self.assertEqual(outcome["runtime_phase"], "AUTOMATED_LIMITED")
        self.assertTrue(self.platform.phase_settings.automated_limited.enabled)

    def test_invalid_mode_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.platform.apply_phase("LIVE")

    def test_mode_persisted_to_disk(self) -> None:
        self.platform.apply_phase("PAPER")
        data = json.loads(self.platform.phase_path.read_text(encoding="utf-8"))
        self.assertEqual(data["mode"], "PAPER")

    def test_api_phase_set_applies_without_restart(self) -> None:
        app = ApiApp(self.platform)
        request = ApiRequest(
            method="POST",
            path="/api/v1/phase",
            query={},
            headers={},
            body=json.dumps({"mode": "PAPER"}).encode("utf-8"),
        )
        response = app._phase_set(request, {}, SimpleNamespace(username="admin"))
        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["runtime_phase"], "PAPER")
        self.assertTrue(payload["execution_enabled"])
        self.assertIsNone(payload["warning"])
        self.assertEqual(app.settings.phase.value, "PAPER")
        self.assertEqual(self.platform.execution.broker.name, "paper")


if __name__ == "__main__":
    unittest.main()
