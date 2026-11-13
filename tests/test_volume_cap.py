"""آزمون سقف حجم فاز و هم‌راستایی وضعیت سناریو در اجرا."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fxars.core.errors import PhaseViolationError
from fxars.domain.enums import Phase, RiskReasonCode, ScenarioStatus
from fxars.domain.models import RiskCheck, RiskDecision
from fxars.risk.account import demo_account
from fxars.risk.service import _cap_decision_volume

from tests.helpers import make_env


def _decision(size: str = "0.17", risk: str = "500") -> RiskDecision:
    now = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
    return RiskDecision(
        decision_id="rd_cap", scenario_id="sc_cap", instrument_id="EURUSD",
        account_snapshot_id="acc_cap", approved=True,
        risk_amount=Decimal(risk), risk_currency="USD", position_size=Decimal(size),
        entry_price=Decimal("1.1000"), stop_loss=Decimal("1.0900"), take_profit=None,
        checks=(RiskCheck("position_size_valid", True, "ok", size, "min 0.01"),),
        policy_version="risk_policy_v1.2", reason_code=RiskReasonCode.APPROVED,
        reason_detail="همه کنترل‌ها عبور کردند.",
        valid_until=now + timedelta(minutes=5), created_at=now, inputs_hash="hash",
    )


class VolumeCapUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = make_env(bars=10)
        cls.instrument = cls.env.instrument

    @classmethod
    def tearDownClass(cls) -> None:
        cls.env.close()

    def test_clamps_and_scales_risk(self) -> None:
        capped = _cap_decision_volume(_decision(), Decimal("0.04"), self.instrument)
        self.assertEqual(capped.position_size, Decimal("0.04"))
        self.assertLess(capped.risk_amount, Decimal("500"))
        self.assertEqual(capped.risk_amount, Decimal("117.65"))
        self.assertIn("phase_volume_cap", [check.code for check in capped.checks])
        size_check = next(c for c in capped.checks if c.code == "position_size_valid")
        self.assertEqual(size_check.value, "0.04")
        self.assertIn("سقف فاز", capped.reason_detail)

    def test_no_change_when_below_cap(self) -> None:
        original = _decision(size="0.03")
        self.assertIs(_cap_decision_volume(original, Decimal("0.04"), self.instrument), original)
        self.assertIs(_cap_decision_volume(original, None, self.instrument), original)

    def test_cap_below_min_lot_is_not_silently_zeroed(self) -> None:
        original = _decision()
        self.assertIs(_cap_decision_volume(original, Decimal("0.001"), self.instrument), original)


class AutomatedExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=600)
        self.platform = self.env.platform
        self.platform.settings = replace(self.platform.settings, phase=Phase.AUTOMATED_LIMITED)
        self.platform.risk.settings = replace(
            self.platform.risk.settings,
            phase=Phase.AUTOMATED_LIMITED,
            risk=replace(
                self.platform.risk.settings.risk,
                risk_per_trade=Decimal("0.10"),
                hard_cap_risk_per_trade=Decimal("0.10"),
            ),
        )
        self._apply_phase(require_triggered=False)
        self.platform.execution.settings = self.platform.settings
        result = self.env.analyze()
        self.scenario = replace(
            result.scenario, status=ScenarioStatus.ARMED, strength=Decimal("0.90"),
            expiry_at=self.env.as_of + timedelta(hours=4),
        )
        self.platform.scenarios.save(self.scenario)

    def tearDown(self) -> None:
        self.env.close()

    def _apply_phase(self, *, require_triggered: bool) -> None:
        self.platform.phase_settings = replace(
            self.platform.phase_settings,
            automated_limited=replace(
                self.platform.phase_settings.automated_limited,
                enabled=True,
                require_triggered_scenario=require_triggered,
                max_volume_per_order=Decimal("0.04"),
                risk_per_trade=Decimal("0.05"),
                max_open_positions=2,
                max_daily_trades=6,
                max_spread_pips=Decimal("50.0"),
            ),
        )

    def test_risk_decision_is_capped_to_phase_limit(self) -> None:
        decision = self.platform.evaluate_risk(
            self.scenario.scenario_id, demo_account(equity="10000", now=self.env.as_of),
        )
        self.assertTrue(decision.approved, decision.reason_detail)
        self.assertEqual(decision.position_size, Decimal("0.04"))
        self.assertIn("phase_volume_cap", decision.checks_passed)

    def test_untriggered_scenario_allowed_only_when_configured(self) -> None:
        self.platform.evaluate_risk(
            self.scenario.scenario_id, demo_account(equity="10000", now=self.env.as_of),
        )
        self.assertFalse(self.platform._scenario_trigger_required())
        intent = self.platform.execution.create_intent(
            self.scenario.scenario_id, client_order_id="cap-armed", actor="test",
        )
        self.assertEqual(intent.volume, Decimal("0.04"))

        self._apply_phase(require_triggered=True)
        self.assertTrue(self.platform._scenario_trigger_required())
        with self.assertRaises(PhaseViolationError):
            self.platform.execution.create_intent(
                self.scenario.scenario_id, client_order_id="cap-armed-2", actor="test",
            )


if __name__ == "__main__":
    unittest.main()
