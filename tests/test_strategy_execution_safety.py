"""آزمون‌های ایمنی مسیر استراتژی و تأیید چهارچشمی ASSISTED.

- سیگنال استراتژی باید از RiskGate و سقف‌های اجرا عبور کند.
- در ASSISTED ارسال سفارش بدون تأیید اپراتور دوم ممنوع است.
- نقش‌های فاقد مجوز اجرا نباید بتوانند سفارش بفرستند.
"""

from __future__ import annotations

import unittest
from datetime import timedelta
from decimal import Decimal

from fxars.config.settings import Settings
from fxars.core.errors import AuthorizationError, PhaseViolationError
from fxars.domain.enums import (
    ApprovalStatus,
    Direction,
    Permission,
    Phase,
    RiskReasonCode,
    Role,
    ScenarioStatus,
)
from fxars.domain.models import RiskDecision, Scenario
from fxars.execution.paper_broker import PaperBroker
from fxars.execution.service import ExecutionService
from fxars.identity.rbac import require_permission
from fxars.risk.account import demo_account, parse_account_snapshot
from fxars.risk.limits import ExecutionLimitInput, execution_block_reason

from tests.helpers import make_env


class StrategyExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=400, phase="PAPER")
        self.candles = self.env.platform.candles.range(
            "EURUSD", "H1", source_id="demo_feed", closed_only=True,
        )
        self.candle = self.candles[-1]
        self.account = parse_account_snapshot(demo_account("10000", now=self.env.as_of))

    def tearDown(self) -> None:
        self.env.close()

    def _analysis(self, *, entry: Decimal | None = None, signal: str = "LONG") -> dict:
        price = self.candle.close
        entry = entry if entry is not None else price
        return {
            "signal": signal,
            "entry": str(entry),
            "stop": str(entry - Decimal("0.0020")),
            "target": str(entry + Decimal("0.0040")),
            "best": {"name": "trend_follow", "score": 0.7},
            "reason": "synthetic",
        }

    def _execute(self, analysis: dict):
        return self.env.platform.strategy_execution.execute(
            instrument_id="EURUSD",
            timeframe="H1",
            analysis=analysis,
            candle=self.candle,
            account=self.account,
            price=self.candle.close,
            pip_size=self.env.instrument.pip_size,
            spread_pips=Decimal("1.0"),
            rates={"USD": Decimal("1")},
            actor="tester",
        )

    def test_signal_goes_through_risk_gate_and_broker(self) -> None:
        outcome = self._execute(self._analysis())
        self.assertEqual(outcome.status, "SUBMITTED", outcome.reason)
        self.assertIsNotNone(outcome.decision)
        self.assertTrue(outcome.decision.approved)
        self.assertIsNotNone(outcome.intent)
        # intent باید به همان تصمیم RiskGate متصل باشد، نه یک شناسه ساختگی.
        self.assertEqual(outcome.intent.risk_decision_id, outcome.decision.decision_id)
        self.assertIn(outcome.intent.status.value, ("FILLED", "PARTIALLY_FILLED", "SUBMITTED"))

    def test_entry_far_from_price_is_rejected_by_gate(self) -> None:
        far_entry = self.candle.close + Decimal("0.0200")
        outcome = self._execute(self._analysis(entry=far_entry))
        self.assertEqual(outcome.status, "RISK_REJECTED", outcome.reason)
        self.assertIsNone(outcome.intent)
        self.assertIn("entry_deviation_ok", outcome.decision.checks_failed)

    def test_killswitch_blocks_strategy_order(self) -> None:
        self.env.platform.killswitch.activate(actor="tester", reason="test")
        outcome = self._execute(self._analysis())
        # RiskGate زودتر از سقف‌های اجرا فعال بودن Kill Switch را رد می‌کند.
        self.assertEqual(outcome.status, "RISK_REJECTED", outcome.reason)
        self.assertIsNone(outcome.intent)
        self.assertIn("kill_switch_inactive", outcome.decision.checks_failed)

    def test_no_trade_signal_creates_nothing(self) -> None:
        outcome = self._execute({"signal": "NO_TRADE"})
        self.assertEqual(outcome.status, "NO_TRADE")
        self.assertIsNone(outcome.intent)


class ExecutionLimitTests(unittest.TestCase):
    def test_paper_requires_paper_broker(self) -> None:
        base = dict(
            phase=Phase.PAPER, execute_orders=True, execution_enabled=True,
            killswitch_active=False, broker_is_real=False,
            position_size=Decimal("0.01"), automated=None, instrument="EURUSD",
            timeframe="H1", scenario_status=ScenarioStatus.TRIGGERED,
            spread_pips=Decimal("1"), max_spread_pips=Decimal("3"),
            open_positions=0, trades_today=0,
        )
        self.assertEqual(execution_block_reason(ExecutionLimitInput(**base)), "PAPER_BROKER_UNAVAILABLE")
        self.assertIsNone(
            execution_block_reason(ExecutionLimitInput(**base, paper_broker=True))
        )

    def test_live_phase_requires_real_broker(self) -> None:
        limits = ExecutionLimitInput(
            phase=Phase.DEMO, execute_orders=True, execution_enabled=True,
            killswitch_active=False, broker_is_real=False,
            position_size=Decimal("0.01"), automated=None, instrument="EURUSD",
            timeframe="H1", scenario_status=ScenarioStatus.TRIGGERED,
            spread_pips=Decimal("1"), max_spread_pips=Decimal("3"),
            open_positions=0, trades_today=0,
        )
        self.assertEqual(execution_block_reason(limits), "REAL_BROKER_UNAVAILABLE")


class AssistedApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240, phase="PAPER")
        self.now = self.env.clock()
        self.price = self.env.candles[-1].close
        self.decision_id = "rd_assisted"
        scenario = Scenario(
            scenario_id="sc_assisted",
            instrument_id="EURUSD",
            timeframe="H1",
            direction=Direction.LONG,
            status=ScenarioStatus.TRIGGERED,
            entry_condition={"type": "price_cross_above", "level": "1.0", "timeframe": "H1"},
            invalidation_condition={"type": "close_below", "level": "0.9", "timeframe": "H1"},
            stop_logic={"type": "structure_low", "level": "0.9"},
            target_logic=({"type": "rr_multiple", "value": 1.5, "price": "1.2"},),
            expiry_at=self.now + timedelta(hours=8),
            evidence_ids=("ev",),
            analysis_run_id="ar",
            decision_explanation="test",
            created_at=self.now,
            updated_at=self.now,
            rules_version="v1",
            config_hash="h",
            strength=0.6,
            risk_decision_id=self.decision_id,
        )
        self.env.platform.scenarios.save(scenario)
        self.env.platform.decisions.save(RiskDecision(
            decision_id=self.decision_id,
            scenario_id="sc_assisted",
            instrument_id="EURUSD",
            account_snapshot_id="acc",
            approved=True,
            risk_amount=Decimal("10"),
            risk_currency="USD",
            position_size=Decimal("0.01"),
            entry_price=self.price,
            stop_loss=self.price - Decimal("0.002"),
            take_profit=self.price + Decimal("0.004"),
            checks=(),
            policy_version="p1",
            reason_code=RiskReasonCode.APPROVED,
            reason_detail="ok",
            valid_until=self.now + timedelta(minutes=10),
            created_at=self.now,
            inputs_hash="h",
        ))
        assisted = Settings.from_dict(
            {"phase": "ASSISTED", "db_path": ":memory:", "environment": "dev"}
        )
        self.execution = ExecutionService(
            settings=assisted,
            clock=self.env.clock,
            scenarios=self.env.platform.scenarios,
            decisions=self.env.platform.decisions,
            orders=self.env.platform.orders,
            killswitch=self.env.platform.killswitch,
            audit=self.env.platform.audit,
            outbox=self.env.platform.outbox,
            broker=PaperBroker(),
            approvals=self.env.platform.approval_service,
        )
        self.approvals = self.env.platform.approval_service

    def tearDown(self) -> None:
        self.env.close()

    def _intent(self):
        return self.execution.create_intent("sc_assisted", actor="op1")

    def _submit(self, intent_id: str):
        return self.execution.submit(
            intent_id, price=self.price, pip_size=self.env.instrument.pip_size, actor="op1",
        )

    def test_submit_without_approval_is_blocked(self) -> None:
        intent = self._intent()
        with self.assertRaises(PhaseViolationError) as ctx:
            self._submit(intent.intent_id)
        self.assertEqual(ctx.exception.details["reason"], "APPROVAL_MISSING")

    def test_four_eyes_requires_different_approver(self) -> None:
        intent = self._intent()
        self.approvals.request(intent.intent_id, actor="op1")
        with self.assertRaises(AuthorizationError):
            self.approvals.approve(intent.intent_id, approved_by="OP1")

    def test_approved_order_submits(self) -> None:
        intent = self._intent()
        self.approvals.request(intent.intent_id, actor="op1")
        approval = self.approvals.approve(intent.intent_id, approved_by="op2")
        self.assertIs(approval.status, ApprovalStatus.APPROVED)
        submitted = self._submit(intent.intent_id)
        self.assertIn(submitted.status.value, ("FILLED", "PARTIALLY_FILLED", "SUBMITTED"))

    def test_rejected_order_cannot_submit(self) -> None:
        intent = self._intent()
        self.approvals.request(intent.intent_id, actor="op1")
        self.approvals.reject(intent.intent_id, rejected_by="op2", reason="manual")
        with self.assertRaises(PhaseViolationError):
            self._submit(intent.intent_id)

    def test_expired_approval_is_rejected(self) -> None:
        intent = self._intent()
        self.approvals.request(intent.intent_id, actor="op1")
        self.approvals.approve(intent.intent_id, approved_by="op2")
        self.env.clock.advance(self.approvals.ttl_seconds + 1)
        with self.assertRaises(PhaseViolationError) as ctx:
            self.approvals.require_approved(intent.intent_id)
        self.assertEqual(ctx.exception.details["reason"], "APPROVAL_EXPIRED")
        stored = self.approvals.get(intent.intent_id)
        self.assertIs(stored.status, ApprovalStatus.EXPIRED)


class TradingPermissionTests(unittest.TestCase):
    def test_tenant_user_cannot_trade(self) -> None:
        with self.assertRaises(AuthorizationError):
            require_permission(Role.TENANT_USER, Permission.EXECUTION_ORDER)
        with self.assertRaises(AuthorizationError):
            require_permission(Role.TENANT_USER, Permission.EXECUTION_APPROVE)

    def test_operator_can_order_but_not_approve(self) -> None:
        require_permission(Role.OPERATOR, Permission.EXECUTION_ORDER)
        with self.assertRaises(AuthorizationError):
            require_permission(Role.OPERATOR, Permission.EXECUTION_APPROVE)

    def test_risk_manager_can_approve(self) -> None:
        require_permission(Role.RISK_MANAGER, Permission.EXECUTION_APPROVE)


if __name__ == "__main__":
    unittest.main()
