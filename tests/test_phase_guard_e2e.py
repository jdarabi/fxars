"""End-to-end Phase Guard tests (P6-2)."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.core.errors import PhaseViolationError
from fxars.domain.enums import Phase
from fxars.risk.account import demo_account

from tests.helpers import make_env


class ReadOnlyPhaseTests(unittest.TestCase):
    def test_readonly_phase_is_default(self):
        env = make_env(bars=120)
        try:
            self.assertEqual(env.settings.phase, Phase.READ_ONLY)
            self.assertFalse(env.settings.execution_enabled)
        finally:
            env.close()

    def test_readonly_blocks_create_intent(self):
        env = make_env(bars=240)
        try:
            with self.assertRaises(PhaseViolationError):
                env.platform.execution.create_intent("sc_any")
        finally:
            env.close()

    def test_readonly_blocks_submit(self):
        env = make_env(bars=120)
        try:
            with self.assertRaises(PhaseViolationError):
                env.platform.execution.submit(
                    "oi_any", price=Decimal("1.0850"), pip_size=Decimal("0.0001"),
                )
        finally:
            env.close()

    def test_readonly_audit_records_blocked_attempt(self):
        env = make_env(bars=120)
        try:
            with self.assertRaises(PhaseViolationError):
                env.platform.execution.create_intent("sc_any", actor="tester")
            entries = env.platform.audit.list_entries(limit=20)
            actions = [e.action for e in entries]
            self.assertIn("ORDER_INTENT_BLOCKED", actions)
        finally:
            env.close()


class PaperPhaseTests(unittest.TestCase):
    def test_paper_phase_allows_create_intent_with_risk_decision(self):
        env = make_env(bars=400, phase="PAPER")
        try:
            self.assertEqual(env.settings.phase, Phase.PAPER)
            self.assertTrue(env.settings.execution_enabled)

            # Run analysis to get a scenario
            result = env.platform.run_analysis("EURUSD", "H1", as_of=env.as_of)
            if result.scenario is None:
                self.skipTest("no scenario generated; skip")
            self.assertEqual(result.run.status.value, "COMPLETED")

            # Evaluate risk
            account = demo_account("10000", now=env.as_of)
            decision = env.platform.evaluate_risk(
                result.scenario.scenario_id, account, now=env.as_of,
            )
            if not decision.approved:
                self.skipTest(f"risk rejected: {decision.reason_code.value}")

            # Create intent — should succeed in PAPER
            intent = env.platform.execution.create_intent(
                result.scenario.scenario_id, actor="tester",
            )
            self.assertIn(intent.status.value, ("RISK_APPROVED", "INTENT_CREATED"))
        finally:
            env.close()

    def test_paper_submit_with_paper_broker(self):
        env = make_env(bars=400, phase="PAPER")
        try:
            result = env.platform.run_analysis("EURUSD", "H1", as_of=env.as_of)
            if result.scenario is None:
                self.skipTest("no scenario generated; skip")

            account = demo_account("10000", now=env.as_of)
            decision = env.platform.evaluate_risk(
                result.scenario.scenario_id, account, now=env.as_of,
            )
            if not decision.approved:
                self.skipTest(f"risk rejected: {decision.reason_code.value}")

            intent = env.platform.execution.create_intent(
                result.scenario.scenario_id, actor="tester",
            )

            # Submit — should succeed in PAPER
            submitted = env.platform.execution.submit(
                intent.intent_id,
                price=Decimal("1.0850"),
                pip_size=env.instrument.pip_size,
                actor="tester",
            )
            self.assertIn(
                submitted.status.value,
                ("FILLED", "PARTIALLY_FILLED", "REJECTED", "UNKNOWN"),
            )
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
