"""FIX-DUAL: تست‌های حالت مشاور و ربات."""
from __future__ import annotations

import unittest

from fxars.config.settings import PhaseSettings
from fxars.domain.enums import Phase

from tests.helpers import make_env


class PhaseEnumTests(unittest.TestCase):
    def test_advisor_not_allowed_order_intents(self):
        self.assertFalse(Phase.ADVISOR.allows_order_intents)
        self.assertTrue(Phase.ADVISOR.is_advisor_mode)
        self.assertFalse(Phase.ADVISOR.is_automation_mode)

    def test_automated_allowed(self):
        self.assertTrue(Phase.AUTOMATED_LIMITED.allows_order_intents)
        self.assertTrue(Phase.AUTOMATED_LIMITED.is_automation_mode)
        self.assertFalse(Phase.AUTOMATED_LIMITED.is_advisor_mode)

    def test_readonly_is_advisor_mode(self):
        self.assertTrue(Phase.READ_ONLY.is_advisor_mode)


class PhaseSettingsTests(unittest.TestCase):
    def test_default_mode_is_advisor(self):
        cfg = PhaseSettings()
        self.assertEqual(cfg.mode, "ADVISOR")
        self.assertFalse(cfg.automated_limited.enabled)

    def test_automated_risk_is_strict(self):
        cfg = PhaseSettings()
        self.assertEqual(str(cfg.automated_limited.max_volume_per_order), "0.01")
        self.assertEqual(cfg.automated_limited.max_open_positions, 1)
        self.assertLessEqual(float(cfg.automated_limited.risk_per_trade), 0.005)


class ExecutionBlockedInAdvisorTests(unittest.TestCase):
    def test_create_intent_blocked_in_advisor(self):
        from fxars.core.errors import PhaseViolationError
        env = make_env(bars=240, users=False)
        try:
            # فاز پیش‌فرض env READ_ONLY است (advisor mode)
            self.assertTrue(env.platform.settings.phase.is_advisor_mode)
            with self.assertRaises(PhaseViolationError):
                env.platform.execution.create_intent("sc_any")
        finally:
            env.close()

    def test_submit_blocked_in_advisor(self):
        from fxars.core.errors import PhaseViolationError
        env = make_env(bars=240, users=False)
        try:
            with self.assertRaises(PhaseViolationError):
                env.platform.execution.submit(
                    "oi_any",
                    price=__import__("decimal").Decimal("1.08"),
                    pip_size=__import__("decimal").Decimal("0.0001"),
                )
        finally:
            env.close()


class TriggerInvalidationTests(unittest.TestCase):
    def test_invalidation_restored(self):
        """FIX-DUAL: invalidation باید در WATCH/ARMED کار کند."""
        from datetime import timedelta
        from decimal import Decimal

        from fxars.decision.trigger import TriggerEvaluator
        from fxars.domain.enums import Direction, ScenarioStatus
        from fxars.domain.models import Candle, PriceZone, Scenario

        env = make_env(bars=240, users=False)
        try:
            evaluator = TriggerEvaluator(env.settings.analysis, env.calendar)
            scenario = Scenario(
                scenario_id="sc_inv", instrument_id="EURUSD", timeframe="H1",
                direction=Direction.LONG, status=ScenarioStatus.WATCH,
                entry_condition={"type": "price_cross_above", "level": "1.0900", "timeframe": "H1"},
                entry_zone=PriceZone("1.0898", "1.0902"),
                invalidation_condition={"type": "close_below", "level": "1.0700", "timeframe": "H1"},
                stop_logic={"type": "structure_low", "level": "1.0700"},
                target_logic=({"type": "rr_multiple", "value": 1.5, "price": "1.0975"},),
                expiry_at=env.as_of + timedelta(hours=8),
                evidence_ids=("ev",), analysis_run_id="ar", decision_explanation="t",
                created_at=env.as_of, updated_at=env.as_of,
                rules_version="v1", config_hash="h", strength=0.6,
            )
            candle = Candle(
                instrument_id="EURUSD", source_id="test", timeframe="H1",
                open_time=env.as_of, open=Decimal("1.0800"), high=Decimal("1.0810"),
                low=Decimal("1.0690"), close=Decimal("1.0700"),
                spread=Decimal("0.0001"), is_closed=True,
                ingested_at=env.as_of, available_at=env.as_of,
            )
            outcome = evaluator.evaluate(scenario, [candle], candle.available_at, env.instrument)
            self.assertEqual(outcome.to_status, ScenarioStatus.INVALIDATED)
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
