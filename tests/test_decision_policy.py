"""آزمون سیاست تصمیم تکمیلی: اعتماد داده، عدم‌قطعیت، امتیاز ترکیبی و گراف شواهد."""

from __future__ import annotations

import unittest
from datetime import timedelta

from fxars.config.decision import DecisionPolicy, UncertaintyPolicy
from fxars.data.trust import compute_data_trust
from fxars.decision.evidence_graph import (
    build_evidence_graph,
    effective_family_strength,
    redundant_evidence,
)
from fxars.decision.score import composite_score
from fxars.decision.uncertainty import compute_uncertainty
from fxars.domain.enums import DecisionAction, Direction, EvidenceFamily
from fxars.domain.models import Decision, Evidence

from tests.helpers import make_env


def evidence(index: int, family: EvidenceFamily, direction: Direction, strength: float,
             as_of, *, module: str | None = None, parameters_hash: str = "") -> Evidence:
    return Evidence(
        evidence_id=f"ev_{index}",
        analysis_run_id="ar_test",
        module_id=module or f"test.{family.value.lower()}",
        module_version="1.0.0",
        instrument_id="EURUSD",
        timeframe="H1",
        observed_at=as_of,
        available_at=as_of,
        direction=direction,
        strength=strength,
        confidence_raw=strength,
        family=family,
        explanation="test",
        parameters_hash=parameters_hash,
    )


class DecisionPolicyValidationTests(unittest.TestCase):
    def test_default_policy_is_valid(self) -> None:
        self.assertEqual(DecisionPolicy().problems(), [])
        self.assertGreater(DecisionPolicy().trust.min_score, 0)

    def test_bad_weights_reported(self) -> None:
        policy = DecisionPolicy.from_dict({"trust": {"w_freshness": 0.9}})
        problems = policy.problems()
        self.assertTrue(any("decision.trust" in item for item in problems))

    def test_bad_uncertainty_order_reported(self) -> None:
        policy = DecisionPolicy.from_dict({"uncertainty": {"wait_threshold": 0.8, "max_total": 0.5}})
        problems = policy.problems()
        self.assertTrue(any("عدم‌قطعیت" in item for item in problems))


class DataTrustTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)

    def tearDown(self) -> None:
        self.env.close()

    def test_empty_series_untrusted(self) -> None:
        trust = compute_data_trust([], timeframe="H1")
        self.assertEqual(trust.status, "UNTRUSTED")
        self.assertEqual(trust.score, 0.0)
        self.assertFalse(trust.is_trusted)

    def test_healthy_series_trusted(self) -> None:
        trust = compute_data_trust(
            self.env.candles, as_of=self.env.as_of, timeframe="H1",
            policy=self.env.settings.decision.trust,
        )
        self.assertGreaterEqual(trust.score, self.env.settings.decision.trust.min_score)
        self.assertTrue(trust.is_trusted)
        self.assertEqual(trust.status, "TRUSTED")
        self.assertGreater(trust.freshness, 0.9)

    def test_stale_and_unreliable_source_untrusted(self) -> None:
        trust = compute_data_trust(
            self.env.candles,
            as_of=self.env.as_of + timedelta(hours=120),
            timeframe="H1",
            policy=self.env.settings.decision.trust,
            source_reliability={"demo_feed": 0.1},
        )
        self.assertEqual(trust.status, "UNTRUSTED")
        self.assertLess(trust.score, self.env.settings.decision.trust.min_score)
        self.assertEqual(trust.freshness, 0.0)
        self.assertTrue(trust.reasons)

    def test_missing_bars_degrade_completeness(self) -> None:
        subset = [candle for index, candle in enumerate(self.env.candles) if index % 3 != 0][-60:]
        expected = {candle.open_time for candle in self.env.candles[-60:]}
        trust = compute_data_trust(
            subset, as_of=self.env.as_of, timeframe="H1",
            expected_bar_times=expected, policy=self.env.settings.decision.trust,
        )
        self.assertLess(trust.completeness, 0.8)


class UncertaintyTests(unittest.TestCase):
    def test_low_uncertainty_for_healthy_inputs(self) -> None:
        breakdown = compute_uncertainty(data_trust=0.95, regime_stability=0.9)
        self.assertEqual(breakdown.level, "LOW")
        self.assertFalse(breakdown.requires_no_trade)
        self.assertLess(breakdown.total, 0.2)

    def test_spread_failure_raises_execution_component(self) -> None:
        breakdown = compute_uncertainty(data_trust=0.95, spread_ok=False)
        self.assertEqual(breakdown.execution, 1.0)
        self.assertTrue(any("اسپرد" in reason for reason in breakdown.reasons))

    def test_combined_risk_factors_critical(self) -> None:
        breakdown = compute_uncertainty(
            data_trust=0.1,
            model_status="uncalibrated",
            regime_uncertain=True,
            conflict_families=1,
            spread_ok=False,
        )
        self.assertGreater(breakdown.total, UncertaintyPolicy().max_total)
        self.assertEqual(breakdown.level, "CRITICAL")
        self.assertTrue(breakdown.requires_no_trade)
        self.assertTrue(breakdown.requires_wait)

    def test_components_sum_to_total(self) -> None:
        policy = UncertaintyPolicy()
        breakdown = compute_uncertainty(
            data_trust=0.7, model_status="none", regime_stability=0.5,
            conflict_families=1, spread_ok=True, policy=policy,
        )
        expected = (
            policy.w_data * breakdown.data
            + policy.w_model * breakdown.model
            + policy.w_regime * breakdown.regime
            + policy.w_conflict * breakdown.conflict
            + policy.w_execution * breakdown.execution
        )
        self.assertAlmostEqual(breakdown.total, expected, places=6)


class CompositeScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=60)

    def tearDown(self) -> None:
        self.env.close()

    def test_aligned_evidence_positive(self) -> None:
        items = [
            evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.8, self.env.as_of),
            evidence(2, EvidenceFamily.TREND, Direction.LONG, 0.7, self.env.as_of),
            evidence(3, EvidenceFamily.MOMENTUM, Direction.LONG, 0.6, self.env.as_of),
        ]
        score = composite_score(items, policy=self.env.settings.decision.evidence)
        self.assertGreater(score.total, 0)
        self.assertEqual(score.conflict_penalty, 0.0)
        self.assertEqual(len(score.contributions), 3)
        self.assertGreater(sum(item.contribution for item in score.contributions), 0)
        self.assertEqual(score.total, 1.0)  # سقف نرمال‌سازی امتیاز ترکیبی

    def test_conflict_penalty_and_no_trade_floor(self) -> None:
        items = [
            evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.9, self.env.as_of),
            evidence(2, EvidenceFamily.STRUCTURE, Direction.SHORT, 0.9, self.env.as_of),
            evidence(3, EvidenceFamily.TREND, Direction.LONG, 0.8, self.env.as_of),
        ]
        decision = Decision(
            action=DecisionAction.NO_TRADE, direction=Direction.NEUTRAL, score=0.0,
            confidence_raw=0.0, family_scores={}, conflicts=("STRUCTURE",), coverage=0.0,
            stability=0.0, reasons=(), evidence_ids=("ev_1", "ev_2", "ev_3"),
            no_trade_reason="EVIDENCE_CONFLICT",
        )
        score = composite_score(
            items, decision=decision, policy=self.env.settings.decision.evidence,
        )
        self.assertGreater(score.conflict_penalty, 0)
        self.assertIn("STRUCTURE", score.conflict_families)
        self.assertLessEqual(score.total, 0.0)

    def test_loss_of_evidence_lowers_total(self) -> None:
        strong = [
            evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.9, self.env.as_of),
            evidence(2, EvidenceFamily.TREND, Direction.LONG, 0.8, self.env.as_of),
        ]
        weak = [
            evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.2, self.env.as_of),
            evidence(2, EvidenceFamily.TREND, Direction.LONG, 0.2, self.env.as_of),
        ]
        strong_score = composite_score(strong, policy=self.env.settings.decision.evidence)
        weak_score = composite_score(weak, policy=self.env.settings.decision.evidence)
        self.assertGreater(strong_score.total, weak_score.total)


class EvidenceGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=60)

    def tearDown(self) -> None:
        self.env.close()

    def test_duplicate_evidence_is_redundant(self) -> None:
        first = evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.8, self.env.as_of,
                         parameters_hash="p1")
        duplicate = evidence(2, EvidenceFamily.STRUCTURE, Direction.LONG, 0.7, self.env.as_of,
                             parameters_hash="p1")
        self.assertEqual(redundant_evidence([first, duplicate]), ["ev_2"])
        graph = build_evidence_graph([first, duplicate], analysis_run_id="ar_x")
        self.assertEqual(graph.redundant_ids, ("ev_2",))
        self.assertFalse(any(node.node_id == "ev:ev_2" for node in graph.nodes))
        self.assertTrue(any(node.node_id == "ev:ev_1" for node in graph.nodes))

    def test_clusters_group_same_family_and_direction(self) -> None:
        items = [
            evidence(1, EvidenceFamily.TREND, Direction.LONG, 0.8, self.env.as_of, module="a"),
            evidence(2, EvidenceFamily.TREND, Direction.LONG, 0.7, self.env.as_of, module="b"),
        ]
        graph = build_evidence_graph(items, analysis_run_id="ar_y")
        self.assertEqual(graph.clusters.get("TREND:LONG"), ("ev_1", "ev_2"))
        self.assertEqual(
            effective_family_strength(items), {"TREND": 0.5},
        )

    def test_decision_node_and_deterministic_id(self) -> None:
        items = [evidence(1, EvidenceFamily.STRUCTURE, Direction.LONG, 0.8, self.env.as_of)]
        decision = Decision(
            action=DecisionAction.LONG, direction=Direction.LONG, score=0.4, confidence_raw=0.7,
            family_scores={"STRUCTURE": 0.4}, conflicts=(), coverage=0.4, stability=1.0,
            reasons=("test",), evidence_ids=("ev_1",), strength=0.7,
        )
        first = build_evidence_graph(items, decision=decision, analysis_run_id="ar_z")
        second = build_evidence_graph(items, decision=decision, analysis_run_id="ar_z")
        self.assertEqual(first.graph_id, second.graph_id)
        decision_nodes = [node for node in first.nodes if node.kind == "DECISION"]
        self.assertEqual(len(decision_nodes), 1)
        self.assertEqual(decision_nodes[0].attributes["score"], 0.4)


class AnalysisIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=600)

    def tearDown(self) -> None:
        self.env.close()

    def test_analysis_meta_contains_supplement_artifacts(self) -> None:
        result = self.env.analyze()
        meta = result.run.decision.get("analysis_meta", {})
        self.assertIn("data_trust", meta)
        self.assertIn("uncertainty", meta)
        self.assertIn("evidence_graph", meta)
        self.assertIn("composite_score", meta)
        self.assertGreaterEqual(
            meta["data_trust"]["score"], self.env.settings.decision.trust.min_score,
        )
        self.assertTrue(str(meta["graph_id"]).startswith("eg_"))
        self.assertGreater(meta["evidence_graph"]["node_count"], 0)
        self.assertIn("total", meta["composite_score"])

    def test_untrusted_data_yields_no_trade(self) -> None:
        policy = self.env.settings.decision
        trust = compute_data_trust(
            self.env.candles, as_of=self.env.as_of + timedelta(hours=120), timeframe="H1",
            policy=policy.trust, source_reliability={"demo_feed": 0.1},
        )
        self.assertEqual(trust.status, "UNTRUSTED")
        # همان قاعده‌ای که سرویس تحلیل اعمال می‌کند: DTS < حد ⇒ NO_TRADE.
        self.assertLess(trust.score, policy.trust.min_score)


if __name__ == "__main__":
    unittest.main()
