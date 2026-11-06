"""Unit tests for fxars.live.advisor.generate_advice + format_advice_text."""
from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.live.advisor import (
    AdviceAction,
    format_advice_text,
    generate_advice,
)


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------
@dataclass
class _FakeDecision:
    action: object
    direction: object
    score: float
    coverage: float = 0.0
    stability: float = 0.0
    strength: float = 0.0
    family_scores: dict | None = None
    no_trade_reason: str | None = None
    evidence_ids: tuple = ()


@dataclass
class _FakeScenario:
    scenario_id: str = "sc_test"
    entry_condition: dict | None = None
    stop_logic: dict | None = None
    target_logic: tuple = ()
    status: object = None
    direction: object = None


@dataclass
class _FakeStatus:
    value: str


@dataclass
class _FakeRiskDecision:
    approved: bool
    checks_failed: tuple = ()
    reason_code: object = None


def _decision_long(score=0.42, **kw):
    return _FakeDecision(
        action="LONG", direction="LONG", score=score,
        coverage=kw.get("coverage", 0.43),
        stability=kw.get("stability", 1.0),
        strength=kw.get("strength", 0.42),
        family_scores=kw.get("family_scores", {"STRUCTURE": 0.12}),
        no_trade_reason=kw.get("no_trade_reason"),
    )


def _decision_short(**kw):
    return _FakeDecision(
        action="SHORT", direction="SHORT", score=kw.get("score", -0.42),
        coverage=kw.get("coverage", 0.43),
        stability=kw.get("stability", 1.0),
        strength=kw.get("strength", 0.42),
        family_scores=kw.get("family_scores", {}),
        no_trade_reason=kw.get("no_trade_reason"),
    )


def _decision_no_trade(reason):
    return _FakeDecision(
        action="NO_TRADE", direction="NEUTRAL", score=0.0,
        no_trade_reason=reason,
    )


def _scenario_with_levels(status="DRAFT"):
    return _FakeScenario(
        scenario_id="sc_1",
        entry_condition={"type": "price_cross_above", "level": "1.08700"},
        stop_logic={"level": "1.08200"},
        target_logic=(
            {"price": "1.09450", "value": 1.5},
            {"price": "1.10200", "value": 3.0},
        ),
        status=_FakeStatus(status),
        direction="LONG",
    )


# ---------------------------------------------------------------------------
# NO TRADE reasons → WAIT / STAY_OUT
# ---------------------------------------------------------------------------
class NoTradeReasonTests(unittest.TestCase):
    def test_data_stale_yields_wait(self):
        advice = generate_advice(
            decision=_decision_no_trade("DATA_STALE"),
            scenario=None, symbol="EURUSD", timeframe="H1",
        )
        self.assertEqual(advice.action, AdviceAction.WAIT)
        self.assertGreaterEqual(advice.confidence, 0.8)
        self.assertIn("کهنه", advice.reason)

    def test_data_quality_fail_yields_stay_out(self):
        advice = generate_advice(
            decision=_decision_no_trade("DATA_QUALITY_FAIL"),
            scenario=None, symbol="EURUSD", timeframe="H1",
        )
        self.assertEqual(advice.action, AdviceAction.STAY_OUT)
        self.assertGreaterEqual(advice.confidence, 0.8)

    def test_evidence_conflict_yields_wait(self):
        advice = generate_advice(
            decision=_decision_no_trade("EVIDENCE_CONFLICT"),
            scenario=None, symbol="EURUSD", timeframe="H1",
        )
        self.assertEqual(advice.action, AdviceAction.WAIT)
        self.assertGreaterEqual(advice.confidence, 0.7)

    def test_insufficient_evidence_yields_wait(self):
        for reason in ("INSUFFICIENT_EVIDENCE", "INSUFFICIENT_COVERAGE"):
            advice = generate_advice(
                decision=_decision_no_trade(reason),
                scenario=None, symbol="EURUSD", timeframe="H1",
            )
            self.assertEqual(advice.action, AdviceAction.WAIT, reason)

    def test_unstable_signal_yields_wait(self):
        advice = generate_advice(
            decision=_decision_no_trade("UNSTABLE_SIGNAL"),
            scenario=None, symbol="EURUSD", timeframe="H1",
        )
        self.assertEqual(advice.action, AdviceAction.WAIT)

    def test_unknown_reason_falls_back_to_stay_out(self):
        advice = generate_advice(
            decision=_decision_no_trade("SOMETHING_NEW"),
            scenario=None, symbol="EURUSD", timeframe="H1",
        )
        self.assertEqual(advice.action, AdviceAction.STAY_OUT)


# ---------------------------------------------------------------------------
# LONG / SHORT with scenario
# ---------------------------------------------------------------------------
class DirectionalAdviceTests(unittest.TestCase):
    def test_long_with_scenario_yields_buy(self):
        advice = generate_advice(
            decision=_decision_long(),
            scenario=_scenario_with_levels("ARMED"),
            symbol="EURUSD", timeframe="H1",
        )
        self.assertEqual(advice.action, AdviceAction.BUY)
        self.assertEqual(advice.scenario_id, "sc_1")
        self.assertEqual(advice.entry, Decimal("1.08700"))
        self.assertEqual(advice.stop, Decimal("1.08200"))
        self.assertEqual(len(advice.targets), 2)
        self.assertGreater(advice.confidence, 0.0)
        self.assertLessEqual(advice.confidence, 1.0)
        self.assertTrue(any("ورود" in s for s in advice.suggestions))

    def test_short_with_scenario_yields_sell(self):
        scenario = _FakeScenario(
            scenario_id="sc_2",
            entry_condition={"type": "price_cross_below", "level": "1.08000"},
            stop_logic={"level": "1.08500"},
            target_logic=({"price": "1.07250", "value": 1.5},),
            status=_FakeStatus("WATCH"),
            direction="SHORT",
        )
        advice = generate_advice(
            decision=_decision_short(),
            scenario=scenario,
            symbol="EURUSD", timeframe="H1",
        )
        self.assertEqual(advice.action, AdviceAction.SELL)
        self.assertEqual(advice.entry, Decimal("1.08000"))
        self.assertEqual(advice.stop, Decimal("1.08500"))

    def test_long_without_scenario_returns_wait(self):
        advice = generate_advice(
            decision=_decision_long(),
            scenario=None,
            symbol="EURUSD", timeframe="H1",
        )
        self.assertEqual(advice.action, AdviceAction.WAIT)
        self.assertIn("سناریو", advice.reason)


# ---------------------------------------------------------------------------
# Risk gate
# ---------------------------------------------------------------------------
class RiskGateTests(unittest.TestCase):
    def test_risk_rejected_yields_stay_out(self):
        risk = _FakeRiskDecision(
            approved=False,
            checks_failed=("SCENARIO_INVALID",),
            reason_code="SCENARIO_INVALID",
        )
        advice = generate_advice(
            decision=_decision_long(),
            scenario=_scenario_with_levels("DRAFT"),
            symbol="EURUSD", timeframe="H1",
            risk_decision=risk,
        )
        self.assertEqual(advice.action, AdviceAction.STAY_OUT)
        self.assertTrue(any("سناریو" in s for s in advice.suggestions))

    def test_risk_kill_switch_suggestion(self):
        risk = _FakeRiskDecision(
            approved=False,
            checks_failed=("KILL_SWITCH_ACTIVE",),
            reason_code="KILL_SWITCH_ACTIVE",
        )
        advice = generate_advice(
            decision=_decision_long(),
            scenario=_scenario_with_levels("ARMED"),
            symbol="EURUSD", timeframe="H1",
            risk_decision=risk,
        )
        self.assertEqual(advice.action, AdviceAction.STAY_OUT)
        self.assertTrue(any("Kill Switch" in s for s in advice.suggestions))

    def test_risk_spread_suggestion(self):
        risk = _FakeRiskDecision(
            approved=False,
            checks_failed=("SPREAD_LIMIT",),
            reason_code="SPREAD_LIMIT",
        )
        advice = generate_advice(
            decision=_decision_long(),
            scenario=_scenario_with_levels("ARMED"),
            symbol="EURUSD", timeframe="H1",
            risk_decision=risk,
        )
        self.assertTrue(any("اسپرد" in s for s in advice.suggestions))


# ---------------------------------------------------------------------------
# Scenario status → suggestions
# ---------------------------------------------------------------------------
class ScenarioStatusTests(unittest.TestCase):
    def _advice_for_status(self, status):
        return generate_advice(
            decision=_decision_long(),
            scenario=_scenario_with_levels(status),
            symbol="EURUSD", timeframe="H1",
        )

    def test_draft_status(self):
        a = self._advice_for_status("DRAFT")
        self.assertTrue(any("DRAFT" in s for s in a.suggestions))

    def test_watch_status(self):
        a = self._advice_for_status("WATCH")
        self.assertTrue(any("WATCH" in s for s in a.suggestions))

    def test_armed_status(self):
        a = self._advice_for_status("ARMED")
        self.assertTrue(any("ARMED" in s for s in a.suggestions))

    def test_triggered_status(self):
        a = self._advice_for_status("TRIGGERED")
        # advisor از عبارت "Trigger" (بدون D) + متن فارسی استفاده می‌کند
        self.assertTrue(
            any("Trigger" in s or "TRIGGERED" in s for s in a.suggestions),
            f"suggestions={a.suggestions}",
        )

    def test_invalidated_status(self):
        a = self._advice_for_status("INVALIDATED")
        self.assertTrue(any("INVALIDATED" in s for s in a.suggestions))

    def test_expired_status(self):
        a = self._advice_for_status("EXPIRED")
        self.assertTrue(any("EXPIRED" in s for s in a.suggestions))


# ---------------------------------------------------------------------------
# confidence / bounds
# ---------------------------------------------------------------------------
class ConfidenceTests(unittest.TestCase):
    def test_confidence_in_bounds(self):
        a = generate_advice(
            decision=_decision_long(strength=1.0, coverage=1.0, stability=1.0),
            scenario=_scenario_with_levels("ARMED"),
            symbol="EURUSD", timeframe="H1",
        )
        self.assertLessEqual(a.confidence, 1.0)
        self.assertGreaterEqual(a.confidence, 0.0)

    def test_low_strength_low_confidence(self):
        a = generate_advice(
            decision=_decision_long(strength=0.0, coverage=0.0, stability=0.0),
            scenario=_scenario_with_levels("ARMED"),
            symbol="EURUSD", timeframe="H1",
        )
        self.assertLess(a.confidence, 0.5)


# ---------------------------------------------------------------------------
# format_advice_text
# ---------------------------------------------------------------------------
class FormatTests(unittest.TestCase):
    def test_format_contains_symbol_and_action(self):
        a = generate_advice(
            decision=_decision_long(),
            scenario=_scenario_with_levels("ARMED"),
            symbol="EURUSD", timeframe="H1",
        )
        text = format_advice_text(a)
        self.assertIn("EURUSD", text)
        self.assertIn("H1", text)
        self.assertIn("BUY", text)
        self.assertIn("اعتماد", text)

    def test_to_dict_is_json_serializable(self):
        import json
        a = generate_advice(
            decision=_decision_long(),
            scenario=_scenario_with_levels("ARMED"),
            symbol="EURUSD", timeframe="H1",
        )
        payload = a.to_dict()
        # نباید خطا بدهد
        json.dumps(payload)
        self.assertEqual(payload["symbol"], "EURUSD")
        self.assertEqual(payload["timeframe"], "H1")
        self.assertEqual(payload["action"], "BUY")


if __name__ == "__main__":
    unittest.main()
