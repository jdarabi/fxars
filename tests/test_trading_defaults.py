"""پیش‌فرض‌های هوشمند تنظیمات معاملات: محاسبه بر اساس سرمایه و اعتبارسنجی."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fxars.api.server import ApiApp, ApiRequest
from fxars.config.settings import AutomatedLimitedSettings, PhaseSettings, Settings
from fxars.config.trading_defaults import (
    apply_automated_updates,
    recommend_trading_settings,
    select_profile,
    validate_automated_settings,
    validate_automated_settings_soft,
)
from fxars.instruments.spec import default_instruments
from fxars.risk.service import RiskService

from tests.helpers import make_env


def _policy(**overrides):
    data = {
        "risk_per_trade": "0.01", "hard_cap_risk_per_trade": "0.10",
        "daily_loss_limit": "0.10", "max_daily_loss_hard_cap": "0.20",
        "drawdown_warn": "0.10", "drawdown_stop": "0.15",
        "max_drawdown_hard_cap": "0.20", "max_open_positions": 2,
        "max_positions_per_symbol": 1, "max_daily_trades": 6,
        "max_spread_pips": "10.0", "min_stop_pips": "3", "max_stop_pips": "150",
    }
    data.update(overrides)
    return Settings.from_dict({"risk": data}).risk


class RecommendationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instruments = default_instruments()

    def test_profiles_follow_equity_tiers(self) -> None:
        self.assertEqual(select_profile(Decimal("100")).key, "micro")
        self.assertEqual(select_profile(Decimal("500")).key, "small")
        self.assertEqual(select_profile(Decimal("1500")).key, "starter")
        self.assertEqual(select_profile(Decimal("10000")).key, "standard")
        self.assertEqual(select_profile(Decimal("50000")).key, "growth")
        self.assertEqual(select_profile(Decimal("250000")).key, "pro")

    def test_recommendation_for_100_usd_is_feasible_and_capped(self) -> None:
        rec = recommend_trading_settings(Decimal("100"), _policy(), self.instruments)
        self.assertEqual(rec["profile"]["key"], "micro")
        self.assertEqual(rec["risk_per_trade"], "0.05")
        self.assertEqual(rec["max_volume_per_order"], "0.04")
        self.assertEqual(rec["max_open_positions"], 1)
        self.assertEqual(rec["max_daily_trades"], 2)
        self.assertLessEqual(Decimal(rec["daily_loss_limit"]), Decimal("0.10"))
        self.assertGreater(Decimal(rec["drawdown_stop"]), Decimal("0.10"))
        self.assertEqual(rec["timeframes"], ["M15", "H1"])
        self.assertIn("EURUSD", rec["instruments"])
        self.assertTrue(any(row["stop_pips"] == 10 and Decimal(row["volume"]) > 0 for row in rec["ladder"]))
        self.assertTrue(any(row["below_min_lot"] for row in rec["ladder"]))

    def test_policy_caps_never_exceeded(self) -> None:
        policy = _policy(
            hard_cap_risk_per_trade="0.01", daily_loss_limit="0.02",
            max_open_positions=1, max_daily_trades=2, max_spread_pips="2.0",
        )
        rec = recommend_trading_settings(Decimal("100"), policy, self.instruments)
        self.assertLessEqual(Decimal(rec["risk_per_trade"]), Decimal("0.01"))
        self.assertLessEqual(Decimal(rec["daily_loss_limit"]), Decimal("0.02"))
        self.assertEqual(rec["max_open_positions"], 1)
        self.assertEqual(rec["max_daily_trades"], 2)
        self.assertLessEqual(Decimal(rec["max_spread_pips"]), Decimal("2.0"))
        self.assertIn("risk_per_trade", rec["capped_by_policy"])

    def test_infeasible_equity_keeps_min_lot_with_warning(self) -> None:
        rec = recommend_trading_settings(Decimal("20"), _policy(), self.instruments)
        self.assertEqual(rec["max_volume_per_order"], "0.01")
        self.assertTrue(any("حداقل سرمایه" in warning for warning in rec["warnings"]))


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instruments = default_instruments()
        self.policy = _policy()
        self.base = replace(
            AutomatedLimitedSettings(), drawdown_stop=Decimal("0.15"),
            risk_per_trade=Decimal("0.01"), daily_loss_limit=Decimal("0.05"),
            instruments=("EURUSD",), timeframes=("M15", "H1"),
        )

    def test_valid_settings_pass(self) -> None:
        self.assertEqual(validate_automated_settings(self.base, self.policy, self.instruments), [])

    def test_risk_above_hard_cap_rejected(self) -> None:
        bad = replace(self.base, risk_per_trade=self.policy.hard_cap_risk_per_trade + Decimal("0.01"))
        self.assertTrue(any("ریسک هر معامله" in error for error in
                            validate_automated_settings(bad, self.policy, self.instruments)))

    def test_positions_above_policy_rejected(self) -> None:
        bad = replace(self.base, max_open_positions=self.policy.max_open_positions + 1)
        self.assertTrue(any("پوزیشن" in error for error in
                            validate_automated_settings(bad, self.policy, self.instruments)))

    def test_empty_timeframes_and_instruments_rejected(self) -> None:
        bad = replace(self.base, timeframes=(), instruments=())
        errors = validate_automated_settings(bad, self.policy, self.instruments)
        self.assertTrue(any("تایم‌فریم" in error for error in errors))
        self.assertTrue(any("نماد" in error for error in errors))

    def test_unknown_instrument_rejected(self) -> None:
        bad = replace(self.base, instruments=("EURUSD", "FAKE"))
        errors = validate_automated_settings(bad, self.policy, self.instruments)
        self.assertTrue(any("بدون مشخصات" in error for error in errors))

    def test_policy_caps_become_warnings_not_errors(self) -> None:
        above = replace(
            self.base, risk_per_trade=self.policy.hard_cap_risk_per_trade + Decimal("0.01"),
            max_open_positions=self.policy.max_open_positions + 1,
            max_daily_trades=self.policy.max_daily_trades + 1,
            max_spread_pips=self.policy.max_spread_pips + Decimal("1"),
        )
        errors, warnings = validate_automated_settings_soft(above, self.policy, self.instruments)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 4)

    def test_symbol_outside_suggested_list_is_only_warning(self) -> None:
        broad = replace(self.base, instruments=("EURUSD", "DXY"))
        errors, warnings = validate_automated_settings_soft(broad, self.policy, self.instruments)
        self.assertEqual(errors, [])
        self.assertTrue(any("خارج از فهرست پیشنهادی" in warning for warning in warnings))

    def test_structural_errors_survive_soft_mode(self) -> None:
        bad = replace(self.base, timeframes=("X1",), max_volume_per_order=Decimal("0"))
        errors, _ = validate_automated_settings_soft(bad, self.policy, self.instruments)
        self.assertTrue(any("تایم‌فریم" in error for error in errors))
        self.assertTrue(any("حجم" in error for error in errors))

    def test_updates_are_coerced_and_unknown_keys_rejected(self) -> None:
        updated = apply_automated_updates(self.base, {
            "risk_per_trade": "0.02",
            "max_open_positions": "2",
            "timeframes": ["m15", "H1", "H1"],
            "instruments": ["eurusd"],
        })
        self.assertEqual(updated.risk_per_trade, Decimal("0.02"))
        self.assertEqual(updated.max_open_positions, 2)
        self.assertEqual(updated.timeframes, ("M15", "H1"))
        self.assertEqual(updated.instruments, ("EURUSD",))
        with self.assertRaises(ValueError):
            apply_automated_updates(self.base, {"enabled": True})


class RiskOverrideTests(unittest.TestCase):
    def test_phase_fraction_is_capped_by_hard_cap(self) -> None:
        service = RiskService.__new__(RiskService)
        service.settings = Settings.from_dict({
            "risk": {
                "risk_per_trade": "0.01", "hard_cap_risk_per_trade": "0.02",
                "daily_loss_limit": "0.05", "drawdown_warn": "0.05", "drawdown_stop": "0.10",
            },
        })
        policy = service._effective_policy(Decimal("0.05"))
        self.assertEqual(policy.risk_per_trade, Decimal("0.02"))
        self.assertEqual(service._effective_policy(None).risk_per_trade, Decimal("0.01"))


class PlatformApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=60)
        self.platform = self.env.platform
        self._tmp = tempfile.TemporaryDirectory()
        self.platform.phase_path = Path(self._tmp.name) / "phase.json"
        data = PhaseSettings(mode="READ_ONLY").to_dict()
        data["automated_limited"].update({
            "drawdown_stop": "0.10", "risk_per_trade": "0.0025",
            "daily_loss_limit": "0.02", "max_volume_per_order": "0.02",
            "max_open_positions": 1, "max_daily_trades": 2,
            "max_spread_pips": "3.0", "instruments": ["EURUSD"],
            "timeframes": ["M15", "H1"],
        })
        self.platform.phase_path.write_text(json.dumps(data), encoding="utf-8")
        self.platform.phase_settings = PhaseSettings.load(self.platform.phase_path)

    def tearDown(self) -> None:
        self.platform.close()
        self._tmp.cleanup()

    def test_settings_are_persisted_and_applied(self) -> None:
        outcome = self.platform.apply_trading_settings(
            {"max_volume_per_order": "0.03", "risk_per_trade": "0.003", "max_open_positions": 2},
        )
        self.assertEqual(outcome["runtime_phase"], "READ_ONLY")
        self.assertEqual(
            self.platform.phase_settings.automated_limited.max_volume_per_order,
            Decimal("0.03"),
        )
        self.assertIs(
            self.platform.strategy_execution.phase_settings,
            self.platform.phase_settings,
        )
        disk = json.loads(self.platform.phase_path.read_text(encoding="utf-8"))
        self.assertEqual(disk["automated_limited"]["max_volume_per_order"], "0.03")

    def test_invalid_update_does_not_touch_disk(self) -> None:
        before = self.platform.phase_path.read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            self.platform.apply_trading_settings({"timeframes": ["X1"]})
        self.assertEqual(self.platform.phase_path.read_text(encoding="utf-8"), before)

    def test_above_policy_needs_confirmation_and_is_not_saved_silently(self) -> None:
        before = self.platform.phase_path.read_text(encoding="utf-8")
        outcome = self.platform.apply_trading_settings({"max_open_positions": 99})
        self.assertFalse(outcome["saved"])
        self.assertTrue(outcome["requires_confirmation"])
        self.assertTrue(outcome["warnings"])
        self.assertEqual(self.platform.phase_path.read_text(encoding="utf-8"), before)

        confirmed = self.platform.apply_trading_settings(
            {"max_open_positions": 99}, confirm_warnings=True,
        )
        self.assertTrue(confirmed["saved"])
        self.assertEqual(confirmed["automated_limited"]["max_open_positions"], 99)
        disk = json.loads(self.platform.phase_path.read_text(encoding="utf-8"))
        self.assertEqual(disk["automated_limited"]["max_open_positions"], 99)

    def test_api_get_returns_recommendation_for_equity(self) -> None:
        app = ApiApp(self.platform)
        handler = next(
            handler for method, pattern, handler, _, _ in app.routes
            if method == "GET" and pattern.match("/api/v1/trading/settings")
        )
        request = ApiRequest(
            method="GET", path="/api/v1/trading/settings",
            query={"equity": ["250"]}, headers={}, body=b"",
        )
        response = handler(request, {}, SimpleNamespace(username="admin"))
        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["equity"], "250")
        self.assertEqual(payload["recommendation"]["profile"]["key"], "small")

    def test_api_post_applies_settings(self) -> None:
        app = ApiApp(self.platform)
        handler = next(
            handler for method, pattern, handler, _, _ in app.routes
            if method == "POST" and pattern.match("/api/v1/trading/settings")
        )
        request = ApiRequest(
            method="POST", path="/api/v1/trading/settings", query={}, headers={},
            body=json.dumps({"automated_limited": {"max_daily_trades": 3}}).encode("utf-8"),
        )
        response = handler(request, {}, SimpleNamespace(username="admin"))
        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["automated_limited"]["max_daily_trades"], 3)
        self.assertEqual(self.platform.phase_settings.automated_limited.max_daily_trades, 3)

    def test_api_post_requires_confirmation_for_policy_overflow(self) -> None:
        app = ApiApp(self.platform)
        handler = next(
            handler for method, pattern, handler, _, _ in app.routes
            if method == "POST" and pattern.match("/api/v1/trading/settings")
        )
        before = self.platform.phase_path.read_text(encoding="utf-8")
        body = {"automated_limited": {"max_open_positions": 99}}
        response = handler(
            ApiRequest(method="POST", path="/api/v1/trading/settings", query={},
                       headers={}, body=json.dumps(body).encode("utf-8")),
            {}, SimpleNamespace(username="admin"),
        )
        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertTrue(payload["requires_confirmation"])
        self.assertFalse(payload["saved"])
        self.assertTrue(payload["warnings"])
        self.assertEqual(self.platform.phase_path.read_text(encoding="utf-8"), before)

        body["confirm_warnings"] = True
        response = handler(
            ApiRequest(method="POST", path="/api/v1/trading/settings", query={},
                       headers={}, body=json.dumps(body).encode("utf-8")),
            {}, SimpleNamespace(username="admin"),
        )
        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertTrue(payload["saved"])
        self.assertEqual(payload["automated_limited"]["max_open_positions"], 99)
        disk = json.loads(self.platform.phase_path.read_text(encoding="utf-8"))
        self.assertEqual(disk["automated_limited"]["max_open_positions"], 99)


if __name__ == "__main__":
    unittest.main()
