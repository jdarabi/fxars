"""آزمون مدیریت ریسک: اندازه موقعیت، کنترل‌ها و Kill Switch."""

from __future__ import annotations

import unittest
from datetime import timedelta
from decimal import Decimal

from fxars.domain.enums import Direction, ScenarioStatus
from fxars.domain.models import AccountSnapshot, Candle, EconomicEvent, PriceZone, Scenario
from fxars.risk.gate import RiskContext, RiskGate
from fxars.risk.sizing import SizingInput, calculate_position_size
from tests.helpers import make_env


def make_scenario(env, *, direction=Direction.LONG, entry="1.0900", stop="1.0850",
                  strength=0.6, status=ScenarioStatus.WATCH, expiry_hours=8) -> Scenario:
    return Scenario(
        scenario_id="sc_risk", instrument_id="EURUSD", timeframe="H1", direction=direction,
        status=status,
        entry_condition={"type": "price_cross_above" if direction is Direction.LONG else "price_cross_below",
                         "level": entry, "timeframe": "H1", "require_closed_candle": True},
        entry_zone=PriceZone(Decimal(entry) - Decimal("0.0002"), Decimal(entry) + Decimal("0.0002")),
        invalidation_condition={"type": "close_below" if direction is Direction.LONG else "close_above",
                                "level": stop, "timeframe": "H1"},
        stop_logic={"type": "structure_low", "level": stop, "buffer_pips": 5},
        target_logic=({"type": "rr_multiple", "value": 1.5, "price": "1.0975"},),
        expiry_at=env.as_of + timedelta(hours=expiry_hours),
        evidence_ids=("ev_1",), analysis_run_id="ar_test", decision_explanation="test",
        created_at=env.as_of, updated_at=env.as_of, rules_version="v1", config_hash="hash", strength=strength,
    )


def make_account(env, **overrides) -> AccountSnapshot:
    values = dict(
        snapshot_id="acc_test", account_id="demo", currency="USD", balance="10000", equity="10000",
        free_margin="10000", margin_used="0", peak_equity="10000", daily_pnl="0", leverage="100",
        open_positions=0, taken_at=env.as_of, positions=(),
    )
    values.update(overrides)
    return AccountSnapshot(**values)


class SizingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=100)

    def tearDown(self) -> None:
        self.env.close()

    def test_standard_sizing(self) -> None:
        result = calculate_position_size(SizingInput(
            equity=Decimal("10000"), risk_fraction=Decimal("0.0025"),
            entry_price=Decimal("1.0900"), stop_price=Decimal("1.0850"),
            instrument=self.env.instrument,
        ))
        self.assertTrue(result.valid)
        self.assertEqual(result.risk_amount, Decimal("25.00"))
        self.assertEqual(result.stop_pips, Decimal("50"))
        self.assertEqual(result.pip_value_per_lot, Decimal("10.0000"))
        self.assertEqual(result.volume, Decimal("0.04"))
        self.assertLessEqual(result.estimated_loss_at_stop, Decimal("25.00"))

    def test_below_min_lot(self) -> None:
        result = calculate_position_size(SizingInput(
            equity=Decimal("100"), risk_fraction=Decimal("0.001"),
            entry_price=Decimal("1.0900"), stop_price=Decimal("1.0000"),
            instrument=self.env.instrument,
        ))
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "BELOW_MIN_LOT")
        self.assertEqual(result.volume, Decimal("0"))

    def test_zero_stop_distance(self) -> None:
        result = calculate_position_size(SizingInput(
            equity=Decimal("10000"), risk_fraction=Decimal("0.0025"),
            entry_price=Decimal("1.0900"), stop_price=Decimal("1.0900"),
            instrument=self.env.instrument,
        ))
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "STOP_DISTANCE_ZERO")

    def test_jpy_quote_conversion(self) -> None:
        instrument = self.env.platform.instruments.get("USDJPY")
        result = calculate_position_size(SizingInput(
            equity=Decimal("10000"), risk_fraction=Decimal("0.0025"),
            entry_price=Decimal("150.00"), stop_price=Decimal("149.50"),
            instrument=instrument, quote_to_account_rate=Decimal("0.0067"),
        ))
        self.assertTrue(result.valid)
        self.assertGreater(result.volume, Decimal("0"))
        self.assertLess(result.estimated_loss_at_stop, Decimal("30"))


class GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)
        self.gate = RiskGate(self.env.settings.risk, self.env.platform.killswitch, self.env.calendar)
        self.candle = Candle(
            instrument_id="EURUSD", source_id="test", timeframe="H1",
            open_time=self.env.as_of - timedelta(hours=1),
            open="1.0870", high="1.0890", low="1.0860", close="1.0880",
            spread=Decimal("0.00010"), is_closed=True,
            ingested_at=self.env.as_of, available_at=self.env.as_of,
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

    def test_approval_path(self) -> None:
        decision = self.gate.evaluate(self.context())
        self.assertTrue(decision.approved, decision.reason_detail)
        self.assertEqual(decision.reason_code.value, "APPROVED")
        self.assertGreater(decision.position_size, Decimal("0"))
        self.assertTrue(decision.checks_failed == ())
        self.assertGreater(decision.valid_until, self.env.as_of)

    def test_missing_account_rejected(self) -> None:
        decision = self.gate.evaluate(self.context(account=None))
        self.assertFalse(decision.approved)
        self.assertIn("account_snapshot_fresh", decision.checks_failed)

    def test_missing_instrument_rejected(self) -> None:
        decision = self.gate.evaluate(self.context(instrument=None, instruments={}))
        self.assertFalse(decision.approved)
        self.assertIn("instrument_spec_valid", decision.checks_failed)

    def test_stale_account_rejected(self) -> None:
        account = make_account(self.env, taken_at=self.env.as_of - timedelta(hours=1))
        decision = self.gate.evaluate(self.context(account=account))
        self.assertIn("account_snapshot_fresh", decision.checks_failed)

    def test_stale_market_data_rejected(self) -> None:
        decision = self.gate.evaluate(self.context(now=self.env.as_of + timedelta(days=7)))
        self.assertFalse(decision.approved)
        self.assertIn("data_fresh", decision.checks_failed)

    def test_kill_switch_rejected(self) -> None:
        self.env.platform.killswitch.activate(actor="risk", reason="test")
        decision = self.gate.evaluate(self.context())
        self.assertFalse(decision.approved)
        self.assertIn("kill_switch_inactive", decision.checks_failed)

    def test_daily_loss_limit(self) -> None:
        account = make_account(self.env, daily_pnl="-300")
        decision = self.gate.evaluate(self.context(account=account))
        self.assertIn("daily_loss_within_limit", decision.checks_failed)

    def test_drawdown_limit(self) -> None:
        account = make_account(self.env, equity="9000", peak_equity="12000")
        decision = self.gate.evaluate(self.context(account=account))
        self.assertIn("drawdown_within_limit", decision.checks_failed)

    def test_max_open_positions(self) -> None:
        account = make_account(self.env, open_positions=3)
        decision = self.gate.evaluate(self.context(account=account))
        self.assertIn("max_open_trades_ok", decision.checks_failed)

    def test_blackout(self) -> None:
        event = EconomicEvent(
            event_id="e1", indicator="NFP", currency="USD", country="US",
            event_time=self.env.as_of, published_at=None, available_at=self.env.as_of,
            importance="HIGH", actual="200", forecast="180",
        )
        decision = self.gate.evaluate(self.context(events=(event,)))
        self.assertIn("event_blackout_ok", decision.checks_failed)

    def test_weak_signal(self) -> None:
        decision = self.gate.evaluate(self.context(scenario=make_scenario(self.env, strength=0.05)))
        self.assertIn("signal_strength", decision.checks_failed)

    def test_spread_limit(self) -> None:
        candle = Candle(
            instrument_id="EURUSD", source_id="test", timeframe="H1",
            open_time=self.env.as_of - timedelta(hours=1), open="1.0870", high="1.0890", low="1.0860",
            close="1.0880", spread=Decimal("0.00100"), is_closed=True,
            ingested_at=self.env.as_of, available_at=self.env.as_of,
        )
        decision = self.gate.evaluate(self.context(candle=candle))
        self.assertIn("spread_within_limit", decision.checks_failed)

    def test_expired_scenario(self) -> None:
        scenario = make_scenario(self.env, expiry_hours=1)
        decision = self.gate.evaluate(self.context(scenario=scenario, now=self.env.as_of + timedelta(hours=2)))
        self.assertIn("scenario_valid", decision.checks_failed)


class KillSwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=100)

    def tearDown(self) -> None:
        self.env.close()

    def test_toggle_and_audit(self) -> None:
        switch = self.env.platform.killswitch
        self.assertFalse(switch.is_active())
        switch.activate(actor="risk_manager", reason="emergency")
        self.assertTrue(switch.is_active())
        switch.deactivate(actor="risk_manager", reason="resolved")
        self.assertFalse(switch.is_active())
        entries = [entry for entry in self.env.platform.audit.list_entries(limit=20)
                   if entry.action == "KILL_SWITCH_CHANGED"]
        self.assertEqual(len(entries), 2)

    def test_reason_required(self) -> None:
        from fxars.core.errors import ValidationError

        with self.assertRaises(ValidationError):
            self.env.platform.killswitch.activate(actor="risk", reason="")


if __name__ == "__main__":
    unittest.main()
