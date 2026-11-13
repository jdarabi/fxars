"""اعتبارسنجی پیکربندی: قواعد سازگاری نباید اجازهٔ بالا آمدن تنظیمات متناقض بدهند."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fxars.config.settings import DEFAULT_CONFIG_PATH, Settings


class SettingsInvariantTests(unittest.TestCase):
    def test_defaults_are_valid(self) -> None:
        Settings.from_dict({})

    def test_risk_per_trade_above_hard_cap_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Settings.from_dict({
                "risk": {"risk_per_trade": "0.04", "hard_cap_risk_per_trade": "0.03"},
            })
        self.assertIn("hard_cap_risk_per_trade", str(ctx.exception))

    def test_drawdown_order_is_enforced(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Settings.from_dict({
                "risk": {"drawdown_warn": "0.20", "drawdown_stop": "0.10"},
            })
        self.assertIn("drawdown", str(ctx.exception))

    def test_absurd_currency_exposure_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Settings.from_dict({"risk": {"max_currency_exposure": "50.0"}})

    def test_scenario_expiry_drift_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Settings.from_dict({"analysis": {"scenario_expiry_bars": 240}})
        self.assertIn("scenario_expiry_bars", str(ctx.exception))

    def test_backtest_risk_cap(self) -> None:
        with self.assertRaises(ValueError):
            Settings.from_dict({"backtest": {"risk_per_trade": "0.04"}})

    def test_active_config_file_is_consistent(self) -> None:
        settings = Settings.load(DEFAULT_CONFIG_PATH)
        self.assertEqual(settings.analysis.scenario_expiry_bars, 8)
        self.assertLess(settings.risk.drawdown_warn, settings.risk.drawdown_stop)

    def test_unknown_kms_provider_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Settings.from_dict({"security": {"kms_provider": "aws"}})
        self.assertIn("kms_provider", str(ctx.exception))

    def test_weak_pbkdf2_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Settings.from_dict({"security": {"pbkdf2_iterations": 1_000}})
        self.assertIn("pbkdf2_iterations", str(ctx.exception))

    def test_kms_provider_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"environment": "dev", "db_path": ":memory:"}), encoding="utf-8")
            with mock.patch.dict("os.environ", {"FXARS_KMS_PROVIDER": "env"}):
                settings = Settings.load(path)
            self.assertEqual(settings.security.kms_provider, "env")


class DemoModeGuardTests(unittest.TestCase):
    def _write_config(self, directory: str, environment: str) -> Path:
        path = Path(directory) / "settings.json"
        path.write_text(json.dumps({"environment": environment, "db_path": ":memory:"}), encoding="utf-8")
        return path

    def test_demo_flag_rejected_outside_dev(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_config(tmp, "prod")
            with mock.patch.dict("os.environ", {"FXARS_ENABLE_DEMO": "1", "FXARS_SECRET_KEY": "x" * 40}):
                with self.assertRaises(ValueError) as ctx:
                    Settings.load(path)
            self.assertIn("FXARS_ENABLE_DEMO", str(ctx.exception))

    def test_demo_flag_allowed_in_dev(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_config(tmp, "dev")
            with mock.patch.dict("os.environ", {"FXARS_ENABLE_DEMO": "1"}):
                settings = Settings.load(path)
            self.assertEqual(settings.environment, "dev")


if __name__ == "__main__":
    unittest.main()
