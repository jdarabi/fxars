"""End-to-end paper trading test with file-based database (P6-5)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.config.settings import Settings
from fxars.domain.enums import OrderStatus
from fxars.domain.models import BrokerOrder
from fxars.execution.reconciliation import ReconciliationService
from fxars.platform import Platform
from fxars.storage.db import Database

from tests.helpers import Clock, make_env


class _AlwaysUnknownBroker:
    """Deterministic broker that always returns UNKNOWN (for reconciliation tests)."""

    name = "always_unknown"

    def submit(self, intent, *, price, pip_size, now=None):
        from datetime import datetime as _dt

        from fxars.core.ids import stable_id

        moment = now or _dt.now(UTC)
        order = BrokerOrder(
            broker_order_id=stable_id("bo", intent.client_order_id, "unknown", length=20),
            intent_id=intent.intent_id,
            status=OrderStatus.UNKNOWN,
            symbol=intent.instrument_id,
            requested_volume=intent.volume,
            filled_volume=Decimal("0"),
            average_price=None,
            updated_at=moment,
            message="forced unknown",
        )
        return order, []

    def query(self, client_order_id):
        return None


class PaperTradingE2ETests(unittest.TestCase):
    """Use make_env with PAPER phase for reliable scenario generation."""

    def setUp(self):
        self.env = make_env(bars=800, phase="PAPER")
        self.assertIsNotNone(self.env.platform.execution.broker)

    def tearDown(self):
        self.env.close()

    def _scenario_and_risk(self):
        """Run analysis + risk; return (scenario, decision) or skip."""
        analysis = self.env.platform.run_analysis("EURUSD", "H1", as_of=self.env.as_of)
        if analysis.scenario is None:
            self.skipTest("no scenario generated; skip pipeline")
        from fxars.risk.account import demo_account, parse_account_snapshot
        account = parse_account_snapshot(demo_account("10000", now=self.env.as_of))
        decision = self.env.platform.evaluate_risk(
            analysis.scenario.scenario_id, account, now=self.env.as_of,
        )
        if not decision.approved:
            self.skipTest(f"risk rejected: {decision.reason_code.value}")
        return analysis.scenario, decision

    def test_full_paper_pipeline(self):
        scenario, decision = self._scenario_and_risk()
        print(f"[E2E] scenario: {scenario.scenario_id} risk={decision.reason_code.value}")

        intent = self.env.platform.execution.create_intent(
            scenario.scenario_id, actor="e2e",
        )
        print(f"[E2E] intent: {intent.intent_id} status={intent.status.value}")
        self.assertIn(intent.status.value, ("RISK_APPROVED", "INTENT_CREATED"))

        candles = self.env.platform.candles.range(
            "EURUSD", "H1", source_id="demo_feed", closed_only=True,
        )
        price = candles[-1].close
        pip = self.env.instrument.pip_size

        submitted = self.env.platform.execution.submit(
            intent.intent_id, price=price, pip_size=pip, actor="e2e",
        )
        print(f"[E2E] submitted: status={submitted.status.value}")
        self.assertIn(
            submitted.status.value,
            ("FILLED", "PARTIALLY_FILLED", "REJECTED", "UNKNOWN"),
        )

        if submitted.status.value in ("FILLED", "PARTIALLY_FILLED"):
            broker_orders = self.env.platform.db.query(
                "SELECT payload FROM broker_orders WHERE intent_id=?", (intent.intent_id,),
            )
            self.assertGreater(len(broker_orders), 0)
            fills = self.env.platform.db.query(
                "SELECT payload FROM fills WHERE broker_order_id IN "
                "(SELECT broker_order_id FROM broker_orders WHERE intent_id=?)",
                (intent.intent_id,),
            )
            self.assertGreater(len(fills), 0)
            print(f"[E2E] persisted: {len(broker_orders)} broker_order(s), {len(fills)} fill(s)")

    def test_unknown_to_reconciliation(self):
        scenario, _ = self._scenario_and_risk()

        # Use a deterministic broker that always returns UNKNOWN
        self.env.platform.execution.broker = _AlwaysUnknownBroker()
        intent = self.env.platform.execution.create_intent(
            scenario.scenario_id, actor="e2e",
        )
        candles = self.env.platform.candles.range(
            "EURUSD", "H1", source_id="demo_feed", closed_only=True,
        )
        submitted = self.env.platform.execution.submit(
            intent.intent_id, price=candles[-1].close,
            pip_size=self.env.instrument.pip_size, actor="e2e",
        )
        self.assertEqual(submitted.status, OrderStatus.UNKNOWN)
        print(f"[E2E] intent forced to UNKNOWN: {intent.intent_id}")

        svc = ReconciliationService(
            orders=self.env.platform.orders,
            broker=self.env.platform.execution.broker,
            audit=self.env.platform.audit,
            outbox=self.env.platform.outbox,
            clock=self.env.platform.clock,
        )
        results = svc.reconcile_all(actor="e2e")
        self.assertGreaterEqual(len(results), 1)
        for r in results:
            print(
                f"[E2E] reconciled: {r.intent_id}: "
                f"{r.from_status.value} -> {r.to_status.value} ({r.reason})"
            )

        reloaded = self.env.platform.orders.get_intent(intent.intent_id)
        self.assertEqual(reloaded.status, OrderStatus.RECONCILIATION_REQUIRED)


class FilePersistenceTests(unittest.TestCase):
    """File-based DB: state survives close/reopen."""

    def test_persistence_across_reopen(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _P(tmpdir) / "fxars.db"
            from fxars.data.synthetic import generate_candles, generate_reference_candles
            from fxars.instruments.calendar import TradingCalendar, default_holidays

            settings = Settings.from_dict({
                "phase": "PAPER",
                "db_path": str(db_path),
                "environment": "dev",
            })
            calendar = TradingCalendar(default_holidays())
            start = datetime(2026, 2, 1, 22, 0, tzinfo=UTC)
            clock = Clock(start)
            platform = Platform(
                settings, db=Database(str(db_path)),
                clock=clock, calendar=calendar, sync_phase=False,
            )
            platform.bootstrap(create_users=False)
            instrument = platform.instruments.get("EURUSD")
            candles = generate_candles(instrument, start, 800, seed=21, calendar=calendar)
            clock.set(candles[-1].available_at)
            platform.ingestion.ingest(
                candles, instrument_id="EURUSD", source_id="demo_feed", now=clock(),
            )
            reference = generate_reference_candles(
                candles, platform.instruments.get("DXY"), seed=31,
            )
            platform.ingestion.ingest(
                reference, instrument_id="DXY", source_id="demo_ref", now=clock(),
            )
            as_of = candles[-1].available_at

            analysis = platform.run_analysis("EURUSD", "H1", as_of=as_of)
            if analysis.scenario is None:
                platform.close()
                self.skipTest("no scenario generated")
            from fxars.risk.account import demo_account, parse_account_snapshot
            account = parse_account_snapshot(demo_account("10000", now=as_of))
            decision = platform.evaluate_risk(
                analysis.scenario.scenario_id, account, now=as_of,
            )
            if not decision.approved:
                platform.close()
                self.skipTest("risk rejected")
            intent = platform.execution.create_intent(
                analysis.scenario.scenario_id, actor="e2e",
            )
            intent_id = intent.intent_id
            platform.close()

            reopened = Platform(
                Settings.from_dict({
                    "phase": "PAPER",
                    "db_path": str(db_path),
                    "environment": "dev",
                }),
                db=Database(str(db_path)),
                clock=clock,
                calendar=calendar,
                sync_phase=False,
            )
            try:
                reloaded = reopened.orders.get_intent(intent_id)
                self.assertIsNotNone(reloaded)
                self.assertEqual(reloaded.intent_id, intent_id)
                print(f"[E2E] persistence: intent {intent_id} survived reopen")
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
