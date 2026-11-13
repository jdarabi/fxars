"""آزمون حاکمیت: منشأ تصمیم، رجیستری سیاست و Model Risk Tiering."""

from __future__ import annotations

import json
import unittest

from fxars.core.errors import ConflictError, ValidationError
from fxars.governance.models import (
    ModelCard,
    ModelRegistryService,
    ModelTransitionError,
    validate_model_card,
)
from fxars.governance.policy import PolicyRegistry, PolicyValidationError
from fxars.governance.provenance import (
    DecisionProvenanceStore,
    ProvenanceError,
    RecordInput,
)

from tests.helpers import make_env


def tier2_card(**overrides) -> ModelCard:
    values = dict(
        model_id="calibrator",
        version="1.0.0",
        tier=2,
        purpose="احتمال موفقیت سناریو",
        owner="research",
        training_data="EURUSD H1 2019-2024",
        feature_schema="structure,trend,momentum",
        limitations=("بدون اخبار", "فقط M15/H1"),
        metrics={"oos_profit_factor": 1.35, "oos_trades": 420},
        calibration={"ece": 0.03, "method": "reliability"},
        provides_probability=True,
        dataset_snapshot="snap_2024",
        code_hash="codehash",
        config_hash="confighash",
    )
    values.update(overrides)
    return ModelCard(**values)


class ModelCardValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        from fxars.config.decision import GovernancePolicy

        self.policy = GovernancePolicy()

    def test_tier3_forbidden_in_mvp(self) -> None:
        errors = validate_model_card(tier2_card(tier=3), self.policy)
        self.assertTrue(any("Tier 3" in item for item in errors))

    def test_tier2_requires_metrics(self) -> None:
        errors = validate_model_card(tier2_card(metrics={}), self.policy)
        self.assertTrue(any("معیارهای OOS" in item for item in errors))

    def test_probability_requires_calibration(self) -> None:
        errors = validate_model_card(tier2_card(calibration={}), self.policy)
        self.assertTrue(any("کالیبراسیون" in item for item in errors))

    def test_missing_limitations_rejected(self) -> None:
        errors = validate_model_card(tier2_card(limitations=()), self.policy)
        self.assertTrue(any("محدودیت" in item for item in errors))

    def test_valid_card_has_no_errors(self) -> None:
        self.assertEqual(validate_model_card(tier2_card(), self.policy), [])


class ModelRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=60)
        self.registry: ModelRegistryService = self.env.platform.model_registry

    def tearDown(self) -> None:
        self.env.close()

    def test_register_tier3_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.registry.register(tier2_card(tier=3), actor="analyst")

    def test_full_promotion_path(self) -> None:
        self.registry.register(tier2_card(), actor="analyst")
        shadow = self.registry.promote(
            "calibrator", "1.0.0", "SHADOW", actor="analyst", reason="آغاز shadow",
        )
        self.assertEqual(shadow.status, "SHADOW")
        canary = self.registry.promote(
            "calibrator", "1.0.0", "CANARY", actor="analyst", reason="shadow پایدار",
        )
        self.assertEqual(canary.status, "CANARY")
        with self.assertRaises(ValidationError):
            self.registry.promote(
                "calibrator", "1.0.0", "ACTIVE", actor="analyst",
                approved_by="auditor", reason="بدون shadow",
            )
        active = self.registry.promote(
            "calibrator", "1.0.0", "ACTIVE", actor="analyst",
            approved_by="auditor", reason="تأیید مستقل",
            shadow_completed=True, oos_passed=True, independent_approval=True,
            kill_switch_ready=True,
        )
        self.assertEqual(active.status, "ACTIVE")
        self.assertEqual(active.approved_by, "auditor")
        self.assertIsNotNone(active.approved_at)

    def test_activation_requires_independent_approver(self) -> None:
        self.registry.register(tier2_card(), actor="analyst")
        for target in ("SHADOW", "CANARY"):
            self.registry.promote("calibrator", "1.0.0", target, actor="analyst", reason="promote")
        with self.assertRaises(ValidationError):
            self.registry.promote(
                "calibrator", "1.0.0", "ACTIVE", actor="analyst",
                approved_by="analyst", reason="self approval",
                shadow_completed=True, oos_passed=True, independent_approval=True,
            )

    def test_invalid_transition_and_missing_reason(self) -> None:
        self.registry.register(tier2_card(), actor="analyst")
        with self.assertRaises(ValidationError):
            self.registry.promote("calibrator", "1.0.0", "SHADOW", actor="analyst", reason="")
        with self.assertRaises(ModelTransitionError):
            self.registry.promote("calibrator", "1.0.0", "ACTIVE", actor="analyst", reason="jump")

    def test_drift_is_persisted(self) -> None:
        result = self.registry.record_drift(
            "calibrator", drift_type="PSI", value=0.32, threshold=0.25,
        )
        self.assertTrue(result["exceeded"])
        count = self.env.platform.db.scalar("SELECT COUNT(*) FROM model_drift")
        self.assertEqual(int(count), 1)


class PolicyRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=30)
        self.registry: PolicyRegistry = self.env.platform.policy_registry

    def tearDown(self) -> None:
        self.env.close()

    def test_register_creates_draft(self) -> None:
        record = self.registry.register("risk", {"risk_per_trade": 0.005}, actor="analyst", version="v1")
        self.assertEqual(record.status, "DRAFT")
        self.assertEqual(record.kind, "risk")
        self.assertTrue(record.content_hash)

    def test_activate_requires_independent_approval_and_reason(self) -> None:
        self.registry.register("risk", {"risk_per_trade": 0.005}, actor="analyst", version="v1")
        with self.assertRaises(PolicyValidationError):
            self.registry.activate("v1", kind="risk", actor="analyst", approved_by="analyst",
                                   reason="self")
        with self.assertRaises(PolicyValidationError):
            self.registry.activate("v1", kind="risk", actor="analyst", approved_by="auditor",
                                   reason=" ")
        record = self.registry.activate("v1", kind="risk", actor="analyst",
                                        approved_by="auditor", reason="approved")
        self.assertEqual(record.status, "ACTIVE")
        self.assertEqual(self.registry.current("risk").version, "v1")

    def test_activation_retires_previous_version(self) -> None:
        self.registry.register("risk", {"risk_per_trade": 0.005}, actor="analyst", version="v1")
        self.registry.activate("v1", kind="risk", actor="analyst", approved_by="auditor", reason="first")
        self.registry.register("risk", {"risk_per_trade": 0.01}, actor="analyst", version="v2")
        activated = self.registry.activate("v2", kind="risk", actor="analyst",
                                           approved_by="auditor", reason="second")
        self.assertEqual(activated.supersedes, "v1")
        self.assertEqual(self.registry.get("v1", kind="risk").status, "RETIRED")
        self.assertEqual(self.registry.current("risk").version, "v2")

    def test_content_conflict_and_validation(self) -> None:
        self.registry.register("risk", {"risk_per_trade": 0.005}, actor="analyst", version="v1")
        with self.assertRaises(ConflictError):
            self.registry.register("risk", {"risk_per_trade": 0.02}, actor="analyst", version="v1")
        with self.assertRaises(PolicyValidationError):
            self.registry.register("unknown", {"a": 1}, actor="analyst")
        with self.assertRaises(PolicyValidationError):
            self.registry.register("risk", {}, actor="analyst")


class ProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=600)
        self.result = self.env.analyze()
        self.run_id = self.result.run.run_id

    def tearDown(self) -> None:
        self.env.close()

    def test_analysis_records_provenance(self) -> None:
        records = self.env.platform.provenance_store.for_run(self.run_id)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.analysis_run_id, self.run_id)
        self.assertEqual(record.tenant_id, "default")
        self.assertTrue(record.evidence_graph_ref.startswith("eg_"))
        self.assertIn(record.data_quality_status, {"TRUSTED", "DEGRADED", "UNTRUSTED"})
        self.assertTrue(record.reason_codes)
        self.assertEqual(len(record.record_hash), 64)

    def test_chain_is_valid_then_tamper_breaks_it(self) -> None:
        store: DecisionProvenanceStore = self.env.platform.provenance_store
        self.assertTrue(store.verify_chain()["valid"])
        row = self.env.platform.db.query_one(
            "SELECT payload FROM decision_provenance LIMIT 1"
        )
        payload = json.loads(row["payload"])
        payload["decision_status"] = "LONG"
        self.env.platform.db.execute(
            "UPDATE decision_provenance SET payload = ? WHERE record_id = ?",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
             payload["record_id"]),
        )
        verification = store.verify_chain()
        self.assertFalse(verification["valid"])
        self.assertEqual(verification["record_id"], payload["record_id"])

    def test_required_field_missing_rejected(self) -> None:
        store = self.env.platform.provenance_store
        data = RecordInput(
            analysis_run_id="ar_x", decision_id="dec_x", scenario_id=None, tenant_id="default",
            decision_status="LONG", no_trade_reason=None, data_cutoff="2026-01-01T00:00:00Z",
            data_quality_status="TRUSTED", regime="TREND", evidence_graph_ref="eg_x",
            uncertainty_factors={}, risk_gate_result=None, config_hash="",
            code_version="1.8.0", model_versions={}, reason_codes=("LONG",), human_override=None,
        )
        with self.assertRaises(ProvenanceError):
            store.record(data)


if __name__ == "__main__":
    unittest.main()
