"""آزمون‌های پذیرش MVP-1 مطابق AC-01 تا AC-12 سند."""

from __future__ import annotations

import sqlite3
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from fxars.analysis.engine import AnalysisEngine
from fxars.api.server import ApiApp, ApiRequest
from fxars.core.errors import PhaseViolationError
from fxars.decision.scenario import ScenarioBuilder
from fxars.domain.enums import DecisionAction, Direction, EvidenceFamily, ScenarioStatus
from fxars.domain.models import Decision
from fxars.research.protocol import assert_disjoint, split_segments
from tests.helpers import make_env


class AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = make_env(bars=500)
        cls.analysis = cls.env.analyze()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.env.close()

    # AC-01
    def test_ac01_invalid_candle_never_enters_analysis(self) -> None:
        original = self.env.candles[10]
        broken = replace(original, high=original.low - Decimal("0.01"))
        result = self.env.platform.ingestion.ingest(
            [broken], instrument_id="EURUSD", source_id="demo_feed", now=self.env.clock(),
        )
        self.assertEqual(result.quarantined, 1)
        stored = [candle for candle in self.env.platform.candles.range("EURUSD", "H1")
                  if candle.open_time == original.open_time]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].high, original.high)
        self.assertGreaterEqual(int(self.env.platform.db.scalar("SELECT COUNT(*) FROM candle_quarantine")), 1)

    # AC-02
    def test_ac02_analysis_reproducible(self) -> None:
        again = self.env.analyze()
        self.assertEqual(self.analysis.run.run_id, again.run.run_id)
        self.assertEqual(self.analysis.run.result_hash, again.run.result_hash)
        self.assertEqual(self.analysis.run.data_snapshot_id, again.run.data_snapshot_id)

    # AC-03
    def test_ac03_scenario_has_trigger_invalidation_expiry(self) -> None:
        scenario = self.analysis.scenario
        if scenario is None:
            decision = Decision(
                action=DecisionAction.LONG, direction=Direction.LONG, score=0.5, confidence_raw=0.5,
                family_scores={"STRUCTURE": 0.5}, conflicts=(), coverage=0.5, stability=1.0,
                reasons=("acceptance",), evidence_ids=("ev",), strength=0.6,
            )
            builder = ScenarioBuilder(self.env.settings.analysis, self.env.calendar)
            built = builder.build(self.analysis.outcome, decision, run_id="ar_acceptance", rules_version="v1")
            scenario = built.scenario
        self.assertIsNotNone(scenario)
        self.assertIn("type", scenario.entry_condition)
        self.assertIn("level", scenario.invalidation_condition)
        self.assertGreater(scenario.expiry_at, self.env.as_of)
        self.assertTrue(scenario.stop_logic.get("level"))
        self.assertTrue(scenario.target_logic)

    # AC-04
    def test_ac04_decision_has_correlation_and_evidence(self) -> None:
        self.assertTrue(self.analysis.run.correlation_id)
        if self.analysis.decision.action is not DecisionAction.NO_TRADE:
            self.assertTrue(self.analysis.decision.evidence_ids)
            stored_ids = {evidence.evidence_id for evidence in self.analysis.evidences}
            self.assertTrue(set(self.analysis.decision.evidence_ids).issubset(stored_ids | stored_ids))

    # AC-05
    def test_ac05_no_order_path_in_mvp1(self) -> None:
        with self.assertRaises(PhaseViolationError):
            self.env.platform.execution.create_intent(self.analysis.scenario.scenario_id if self.analysis.scenario else "sc_any")
        app = ApiApp(self.env.platform)
        request = ApiRequest(method="GET", path="/api/v1/orders", query={}, headers={}, body=b"")
        response = app.handle(request)
        self.assertEqual(response.status, 404)

    # AC-06
    def test_ac06_risk_gate_rejects_missing_account(self) -> None:
        from fxars.risk.gate import RiskContext, RiskGate
        from fxars.domain.models import Candle

        scenario = self.analysis.scenario
        if scenario is None:
            self.skipTest("سناریویی موجود نیست")
        candle = Candle(
            instrument_id="EURUSD", source_id="test", timeframe="H1",
            open_time=self.env.as_of - timedelta(hours=1), open="1.0800", high="1.0850", low="1.0750",
            close="1.0820", spread=Decimal("0.0001"), is_closed=True,
            ingested_at=self.env.as_of, available_at=self.env.as_of,
        )
        gate = RiskGate(self.env.settings.risk, self.env.platform.killswitch, self.env.calendar)
        decision = gate.evaluate(RiskContext(
            scenario=scenario, account=None, instrument=self.env.instrument, candle=candle,
            events=(), instruments={}, rates={"USD": Decimal("1")}, correlations={}, now=self.env.as_of,
        ))
        self.assertFalse(decision.approved)
        self.assertIn("account_snapshot_fresh", decision.checks_failed)

    # AC-07
    def test_ac07_backtest_costs_are_separated(self) -> None:
        result = self.env.platform.research.run("EURUSD", "H1", persist=False)
        costs = result.run.metrics["costs"]
        for key in ("spread", "commission", "swap", "slippage", "total"):
            self.assertIn(key, costs)

    # AC-08
    def test_ac08_oos_segments_independent(self) -> None:
        split = split_segments(len(self.env.candles), embargo_bars=5)
        assert_disjoint(split)
        self.assertGreaterEqual(split.locked_test.start, split.validation.end + 5)
        self.assertGreaterEqual(split.validation.start, split.train.end + 5)

    # AC-09
    def test_ac09_no_probability_without_calibration(self) -> None:
        payload = self.analysis.decision.to_dict()
        self.assertNotIn("probability", payload)
        for evidence in self.analysis.evidences:
            self.assertNotIn("probability", evidence.to_dict())
            self.assertIn("confidence_raw", evidence.to_dict())

    # AC-10
    def test_ac10_audit_append_only(self) -> None:
        self.assertTrue(self.env.platform.audit_verify()["valid"])
        with self.assertRaises(sqlite3.DatabaseError):
            self.env.platform.db.execute("DELETE FROM audit_events")

    # AC-11
    def test_ac11_stale_data_yields_no_trade(self) -> None:
        later = self.env.as_of + timedelta(days=7)
        result = self.env.platform.run_analysis("EURUSD", "H1", as_of=later)
        self.assertEqual(result.decision.action, DecisionAction.NO_TRADE)
        self.assertEqual(result.decision.no_trade_reason, "DATA_STALE")
        self.assertIsNone(result.scenario)

    # AC-12
    def test_ac12_operational_docs_exist(self) -> None:
        for path in (
            "README.md", "docs/ARCHITECTURE.md", "docs/OPERATIONS.md", "docs/ACCEPTANCE.md",
            "docs/RISK_POLICY.md", "docs/VALIDATION_PROTOCOL.md", "docs/API.md",
        ):
            self.assertTrue(Path(path).exists(), path)


if __name__ == "__main__":
    unittest.main()
