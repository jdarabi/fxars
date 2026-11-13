"""آزمون قفل ریسک، زیان هفتگی، سشن بازار و Kill Switch سه‌سطحی."""

from __future__ import annotations

import unittest
from datetime import timedelta
from decimal import Decimal

from fxars.core.errors import ValidationError
from fxars.domain.enums import RiskLockState, Side
from fxars.domain.models import Candle, ClosedTrade
from fxars.risk.account import demo_account
from fxars.risk.gate import RiskContext, RiskGate
from fxars.risk.killswitch import SCOPE_ACCOUNT, SCOPE_MODULE, SCOPE_SYSTEM
from fxars.risk.lock_lifecycle import RiskLockMachine, RiskLockThresholds

from tests.helpers import make_env
from tests.test_risk import make_account, make_scenario


class RiskLockLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=60)
        self.lock: RiskLockMachine = self.env.platform.risk_lock

    def tearDown(self) -> None:
        self.env.close()

    def test_starts_normal_and_thresholds_follow_policy(self) -> None:
        self.assertIs(self.lock.current(), RiskLockState.NORMAL)
        thresholds = RiskLockThresholds.from_risk_policy(self.env.settings.risk)
        self.assertEqual(thresholds.daily_limit, self.env.settings.risk.daily_loss_limit)
        self.assertEqual(thresholds.drawdown_stop, self.env.settings.risk.drawdown_stop)

    def test_daily_loss_locks_and_stays_locked(self) -> None:
        decision = self.lock.evaluate(daily_loss=Decimal("0.03"))
        self.assertIs(decision.state, RiskLockState.LOCKED_DAILY)
        self.assertTrue(decision.blocks_orders)
        again = self.lock.evaluate(daily_loss=Decimal("0"))
        self.assertIs(again.state, RiskLockState.LOCKED_DAILY)
        self.assertTrue(any("بازبینی دستی" in reason for reason in again.reasons))
        self.assertIs(self.lock.current(), RiskLockState.LOCKED_DAILY)

    def test_warning_does_not_block(self) -> None:
        decision = self.lock.evaluate(drawdown=Decimal("0.06"))
        self.assertIs(decision.state, RiskLockState.WARNING)
        self.assertFalse(decision.blocks_orders)

    def test_weekly_loss_lock(self) -> None:
        decision = self.lock.evaluate(weekly_loss=Decimal("0.07"))
        self.assertIs(decision.state, RiskLockState.LOCKED_WEEKLY)
        self.assertTrue(decision.blocks_orders)

    def test_manual_release_required(self) -> None:
        self.lock.evaluate(daily_loss=Decimal("0.03"))
        with self.assertRaises(ValidationError):
            self.lock.manual_review(actor="risk", reason=" ")
        with self.assertRaises(ValidationError):
            self.lock.manual_review(actor="risk", reason="پرش مستقیم", release=True)
        reviewing = self.lock.manual_review(actor="risk", reason="بازبینی دستی")
        self.assertEqual(reviewing["state"], "MANUAL_REVIEW")
        released = self.lock.manual_review(actor="risk", reason="آزادسازی پس از بازبینی", release=True)
        self.assertEqual(released["state"], "NORMAL")
        self.assertIs(self.lock.current(), RiskLockState.NORMAL)

    def test_kill_switch_locks_until_official_release(self) -> None:
        decision = self.lock.evaluate(kill_switch_active=True)
        self.assertIs(decision.state, RiskLockState.KILL_SWITCH)
        with self.assertRaises(ValidationError):
            self.lock.manual_review(actor="risk", reason="release", release=True)
        self.assertIs(self.lock.current(), RiskLockState.KILL_SWITCH)

    def test_history_records_transitions(self) -> None:
        self.lock.evaluate(daily_loss=Decimal("0.03"))
        status = self.lock.status()
        self.assertTrue(status["history"])
        self.assertEqual(status["history"][-1]["to"], "LOCKED_DAILY")


class GateSupplementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)
        self.candle = Candle(
            instrument_id="EURUSD", source_id="test", timeframe="H1",
            open_time=self.env.as_of - timedelta(hours=1),
            open="1.0870", high="1.0890", low="1.0860", close="1.0880",
            spread=Decimal("0.00010"), is_closed=True,
            ingested_at=self.env.as_of, available_at=self.env.as_of,
        )
        self.gate = RiskGate(
            self.env.settings.risk, self.env.platform.killswitch, self.env.calendar,
            risk_lock=lambda: self.env.platform.risk_lock.current().blocks_orders,
        )

    def tearDown(self) -> None:
        self.env.close()

    def context(self, **overrides) -> RiskContext:
        values = dict(
            scenario=make_scenario(self.env),
            account=make_account(self.env),
            instrument=self.env.instrument,
            candle=self.candle,
            events=(),
            instruments={"EURUSD": self.env.instrument},
            rates={"USD": Decimal("1")},
            correlations={},
            now=self.env.as_of,
        )
        values.update(overrides)
        return RiskContext(**values)

    def test_market_session_check_present(self) -> None:
        decision = self.gate.evaluate(self.context())
        self.assertNotIn("market_open", decision.checks_failed)

    def test_weekend_blocks_market_open(self) -> None:
        decision = self.gate.evaluate(self.context(now=self.env.as_of + timedelta(days=1)))
        self.assertIn("market_open", decision.checks_failed)

    def test_weekly_loss_limit(self) -> None:
        decision = self.gate.evaluate(self.context(weekly_loss_fraction=Decimal("0.10")))
        self.assertIn("weekly_loss_within_limit", decision.checks_failed)
        self.assertEqual(decision.reason_code.value, "WEEKLY_LOSS_LIMIT")

    def test_weekly_loss_within_limit_passes(self) -> None:
        decision = self.gate.evaluate(self.context(weekly_loss_fraction=Decimal("0.01")))
        self.assertNotIn("weekly_loss_within_limit", decision.checks_failed)

    def test_risk_lock_blocks_orders(self) -> None:
        self.env.platform.risk_lock.evaluate(daily_loss=Decimal("0.03"))
        decision = self.gate.evaluate(self.context())
        self.assertIn("risk_lock_clear", decision.checks_failed)


class RiskServiceWeeklyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)

    def tearDown(self) -> None:
        self.env.close()

    def trade(self, net: str, *, closed_at=None, tenant: str = "default") -> ClosedTrade:
        moment = closed_at or (self.env.as_of - timedelta(hours=1))
        return ClosedTrade(
            trade_id="trade_1", intent_id="intent_1", tenant_id=tenant,
            instrument_id="EURUSD", side=Side.BUY, volume=Decimal("0.10"),
            entry_price=Decimal("1.0900"), exit_price=Decimal("1.0800"),
            opened_at=moment - timedelta(hours=1), closed_at=moment,
            gross_profit=Decimal(net), commission=Decimal("0"), swap=Decimal("0"),
            net_profit=Decimal(net),
        )

    def test_loss_fraction_uses_closed_trades(self) -> None:
        self.env.platform.closed_trades.save(self.trade("-100"))
        snapshot = make_account(self.env, equity="10000", peak_equity="10000")
        fraction = self.env.platform.risk._weekly_loss_fraction(snapshot, "default", self.env.as_of)
        self.assertEqual(fraction, Decimal("0.01"))

    def test_profit_does_not_create_weekly_loss(self) -> None:
        self.env.platform.closed_trades.save(self.trade("250"))
        snapshot = make_account(self.env, equity="10000", peak_equity="10000")
        self.assertEqual(
            self.env.platform.risk._weekly_loss_fraction(snapshot, "default", self.env.as_of),
            Decimal("0"),
        )

    def test_service_evaluate_triggers_weekly_lock(self) -> None:
        self.env.platform.closed_trades.save(self.trade("-100"))
        scenario = make_scenario(self.env)
        self.env.platform.scenarios.save(scenario)
        decision = self.env.platform.risk.evaluate(
            scenario.scenario_id,
            demo_account("500", now=self.env.as_of),
            rates={"USD": "1"}, now=self.env.as_of, trades_today=0,
        )
        self.assertIs(self.env.platform.risk_lock.current(), RiskLockState.LOCKED_WEEKLY)
        self.assertFalse(decision.approved)
        second = self.env.platform.risk.evaluate(
            scenario.scenario_id,
            demo_account("500", now=self.env.as_of),
            rates={"USD": "1"}, now=self.env.as_of, trades_today=0,
        )
        self.assertIn("risk_lock_clear", second.checks_failed)


class ScopedKillSwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=30)
        self.switch = self.env.platform.killswitch

    def tearDown(self) -> None:
        self.env.close()

    def test_module_scope_is_isolated(self) -> None:
        self.switch.activate(actor="risk", reason="freeze analysis", scope=SCOPE_MODULE, target="analysis")
        self.assertTrue(self.switch.is_active())
        self.assertTrue(self.switch.is_active(SCOPE_MODULE, "analysis"))
        self.assertFalse(self.switch.is_active(SCOPE_SYSTEM))
        self.assertFalse(self.switch.is_active(SCOPE_ACCOUNT, "acc-1"))
        statuses = self.switch.all_status()
        self.assertTrue(any(item.get("key", "").endswith("MODULE:analysis") for item in statuses))

    def test_account_scope_requires_target(self) -> None:
        with self.assertRaises(ValidationError):
            self.switch.activate(actor="risk", reason="freeze", scope=SCOPE_ACCOUNT, target=" ")


if __name__ == "__main__":
    unittest.main()
