"""آزمون موتور تصمیم، ماشین حالت و ارزیاب شرط‌ها."""

from __future__ import annotations

import unittest
from datetime import timedelta
from decimal import Decimal

from fxars.core.errors import ScenarioTransitionError
from fxars.decision.aggregation import aggregate_evidence, filter_usable
from fxars.decision.scenario import ScenarioBuilder
from fxars.decision.state_machine import ScenarioStateMachine, can_transition
from fxars.decision.trigger import TriggerEvaluator
from fxars.domain.enums import DecisionAction, Direction, EvidenceFamily, ScenarioStatus
from fxars.domain.models import Decision, Evidence, PriceZone
from tests.helpers import make_env


def make_evidence(index: int, family: EvidenceFamily, direction: Direction, strength: float,
                  as_of, *, age_bars: int = 0, expiry=None, instrument="EURUSD") -> Evidence:
    from datetime import timedelta

    observed = as_of - timedelta(hours=age_bars)
    return Evidence(
        evidence_id=f"ev_test_{index}",
        analysis_run_id="ar_test",
        module_id=f"test.{family.value.lower()}",
        module_version="1.0.0",
        instrument_id=instrument,
        timeframe="H1",
        observed_at=observed,
        available_at=observed,
        direction=direction,
        strength=strength,
        confidence_raw=strength,
        family=family,
        explanation="test",
        expiry=expiry,
    )


class AggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)
        self.settings = self.env.settings.analysis
        self.now = self.env.as_of

    def tearDown(self) -> None:
        self.env.close()

    def test_long_decision(self) -> None:
        evidences = [
            make_evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.8, self.now),
            make_evidence(2, EvidenceFamily.TREND, Direction.LONG, 0.7, self.now),
            make_evidence(3, EvidenceFamily.MOMENTUM, Direction.LONG, 0.6, self.now),
        ]
        decision = aggregate_evidence(evidences, self.settings, as_of=self.now, timeframe="H1")
        self.assertEqual(decision.action, DecisionAction.LONG)
        self.assertGreater(decision.score, 0)
        self.assertGreaterEqual(decision.coverage, self.settings.min_coverage)

    def test_conflict_yields_no_trade(self) -> None:
        evidences = [
            make_evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.9, self.now),
            make_evidence(2, EvidenceFamily.STRUCTURE, Direction.SHORT, 0.9, self.now),
            make_evidence(3, EvidenceFamily.TREND, Direction.LONG, 0.8, self.now),
            make_evidence(4, EvidenceFamily.TREND, Direction.SHORT, 0.8, self.now),
            make_evidence(5, EvidenceFamily.MOMENTUM, Direction.LONG, 0.6, self.now),
        ]
        decision = aggregate_evidence(evidences, self.settings, as_of=self.now, timeframe="H1")
        self.assertEqual(decision.action, DecisionAction.NO_TRADE)
        self.assertEqual(decision.no_trade_reason, "EVIDENCE_CONFLICT")
        self.assertIn("STRUCTURE", decision.conflicts)

    def test_low_coverage_yields_no_trade(self) -> None:
        evidences = [make_evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.9, self.now)]
        decision = aggregate_evidence(evidences, self.settings, as_of=self.now, timeframe="H1")
        self.assertEqual(decision.action, DecisionAction.NO_TRADE)
        self.assertIn(decision.no_trade_reason, ("INSUFFICIENT_COVERAGE", "INSUFFICIENT_EVIDENCE"))

    def test_old_evidence_filtered(self) -> None:
        evidences = [make_evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.9, self.now, age_bars=20)]
        usable = filter_usable(evidences, as_of=self.now, timeframe="H1", settings=self.settings)
        self.assertEqual(usable, [])
        decision = aggregate_evidence(evidences, self.settings, as_of=self.now, timeframe="H1")
        self.assertEqual(decision.no_trade_reason, "NO_USABLE_EVIDENCE")

    def test_expired_evidence_filtered(self) -> None:
        evidence = make_evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.9, self.now,
                                 expiry=self.now - timedelta(minutes=1))
        usable = filter_usable([evidence], as_of=self.now, timeframe="H1", settings=self.settings)
        self.assertEqual(usable, [])

    def test_weak_evidence_filtered(self) -> None:
        evidence = make_evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.01, self.now)
        self.assertEqual(filter_usable([evidence], as_of=self.now, timeframe="H1", settings=self.settings), [])


class ScenarioBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=600)
        result = self.env.analyze()
        self.outcome = result.outcome
        self.assertIsNotNone(self.outcome)

    def tearDown(self) -> None:
        self.env.close()

    def test_build_long_scenario_contract(self) -> None:
        decision = Decision(
            action=DecisionAction.LONG, direction=Direction.LONG, score=0.5, confidence_raw=0.6,
            family_scores={"STRUCTURE": 0.4}, conflicts=(), coverage=0.5, stability=1.0,
            reasons=("test",), evidence_ids=("ev_1",), strength=0.6,
        )
        result = ScenarioBuilder(self.env.settings.analysis, self.env.calendar).build(
            self.outcome, decision, run_id="ar_test", rules_version="v1",
        )
        self.assertIsNotNone(result.scenario)
        scenario = result.scenario
        self.assertEqual(scenario.status, ScenarioStatus.DRAFT)
        self.assertEqual(scenario.direction, Direction.LONG)
        self.assertIn("type", scenario.entry_condition)
        self.assertIn("level", scenario.invalidation_condition)
        self.assertLess(Decimal(scenario.stop_logic["level"]), Decimal(scenario.entry_condition["level"]))
        self.assertTrue(scenario.target_logic)
        self.assertGreater(scenario.expiry_at, self.outcome.as_of)
        self.assertIsNotNone(scenario.entry_zone)
        self.assertEqual(len(scenario.evidence_ids), 1)

    def test_build_no_trade_returns_none(self) -> None:
        decision = Decision(
            action=DecisionAction.NO_TRADE, direction=Direction.NEUTRAL, score=0.0, confidence_raw=0.0,
            family_scores={}, conflicts=(), coverage=0.0, stability=0.0, reasons=(), evidence_ids=(),
            no_trade_reason="NO_USABLE_EVIDENCE",
        )
        result = ScenarioBuilder(self.env.settings.analysis, self.env.calendar).build(
            self.outcome, decision, run_id="ar_test", rules_version="v1",
        )
        self.assertIsNone(result.scenario)


class StateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)
        self.machine = ScenarioStateMachine("rules_v1")

    def tearDown(self) -> None:
        self.env.close()

    def test_transition_table(self) -> None:
        self.assertTrue(can_transition(ScenarioStatus.DRAFT, ScenarioStatus.WATCH))
        self.assertTrue(can_transition(ScenarioStatus.WATCH, ScenarioStatus.ARMED))
        self.assertTrue(can_transition(ScenarioStatus.ARMED, ScenarioStatus.TRIGGERED))
        self.assertFalse(can_transition(ScenarioStatus.DRAFT, ScenarioStatus.TRIGGERED))
        self.assertFalse(can_transition(ScenarioStatus.EXPIRED, ScenarioStatus.WATCH))

    def test_invalid_transition_raises(self) -> None:
        scenario = _scenario(self.env)
        with self.assertRaises(ScenarioTransitionError):
            self.machine.transition(scenario, ScenarioStatus.TRIGGERED, actor="tester", reason="invalid")

    def test_transition_records_metadata(self) -> None:
        scenario = _scenario(self.env, status=ScenarioStatus.DRAFT)
        updated, transition = self.machine.transition(
            scenario, ScenarioStatus.WATCH, actor="analyst", reason="evidence", occurred_at=self.env.as_of,
        )
        self.assertEqual(updated.status, ScenarioStatus.WATCH)
        self.assertEqual(transition.actor, "analyst")
        self.assertEqual(transition.from_status, ScenarioStatus.DRAFT)
        self.assertEqual(transition.rules_version, "rules_v1")


class TriggerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)
        self.evaluator = TriggerEvaluator(self.env.settings.analysis, self.env.calendar)

    def tearDown(self) -> None:
        self.env.close()

    def test_expiry(self) -> None:
        scenario = _scenario(self.env, status=ScenarioStatus.WATCH)
        outcome = self.evaluator.evaluate(scenario, [self.candle()], scenario.expiry_at + timedelta(minutes=1), self.env.instrument)
        self.assertEqual(outcome.to_status, ScenarioStatus.EXPIRED)

    def test_invalidation(self) -> None:
        scenario = _scenario(self.env, status=ScenarioStatus.WATCH)
        candle = self.candle(close=Decimal("1.0700"), low=Decimal("1.0690"), high=Decimal("1.0710"))
        outcome = self.evaluator.evaluate(scenario, [candle], candle.available_at, self.env.instrument)
        self.assertEqual(outcome.to_status, ScenarioStatus.INVALIDATED)

    def test_trigger_on_close_beyond_level(self) -> None:
        scenario = _scenario(self.env, status=ScenarioStatus.ARMED)
        candle = self.candle(close=Decimal("1.0900"), high=Decimal("1.0910"), low=Decimal("1.0890"))
        outcome = self.evaluator.evaluate(scenario, [candle], candle.available_at, self.env.instrument)
        self.assertEqual(outcome.to_status, ScenarioStatus.TRIGGERED)

    def test_stale_data_no_transition(self) -> None:
        scenario = _scenario(self.env, status=ScenarioStatus.ARMED, expiry_hours=24 * 30)
        candle = self.candle()
        outcome = self.evaluator.evaluate(scenario, [candle], candle.available_at + timedelta(days=7), self.env.instrument)
        self.assertIsNone(outcome.to_status)
        self.assertEqual(outcome.event, "stale_data")

    def candle(self, **overrides):
        from fxars.domain.models import Candle

        values = dict(
            instrument_id="EURUSD", source_id="test", timeframe="H1",
            open_time=self.env.as_of, open="1.0850", high="1.0860", low="1.0840", close="1.0855",
            spread=Decimal("0.0001"), is_closed=True,
            ingested_at=self.env.as_of, available_at=self.env.as_of,
        )
        values.update(overrides)
        return Candle(**values)


def _scenario(env, status: ScenarioStatus = ScenarioStatus.WATCH, expiry_hours: int = 8):
    from fxars.domain.models import Scenario

    return Scenario(
        scenario_id="sc_test", instrument_id="EURUSD", timeframe="H1", direction=Direction.LONG,
        status=status,
        entry_condition={"type": "price_cross_above", "level": "1.0870", "timeframe": "H1", "require_closed_candle": True},
        entry_zone=PriceZone("1.0860", "1.0880"),
        invalidation_condition={"type": "close_below", "level": "1.0800", "timeframe": "H1"},
        stop_logic={"type": "structure_low", "reference": "last_swing_low", "level": "1.0800", "buffer_pips": 5},
        target_logic=({"type": "rr_multiple", "value": 1.5, "price": "1.0975"},),
        expiry_at=env.as_of + timedelta(hours=expiry_hours),
        evidence_ids=("ev_1",), analysis_run_id="ar_test", decision_explanation="test",
        created_at=env.as_of, updated_at=env.as_of, rules_version="v1", config_hash="hash", strength=0.6,
    )


if __name__ == "__main__":
    unittest.main()
