"""آزمون ثبت نتیجه واقعی معاملات بسته‌شده و گزارش Attribution."""
from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.core.ids import stable_id
from fxars.domain.enums import OrderStatus, OrderType, Phase, Side
from fxars.domain.models import BrokerOrder, ClosedTrade, Fill, OrderIntent, RiskDecision
from fxars.execution.attribution import group_by, summarize
from fxars.execution.close_reconciliation import BrokerClose, CloseReconciliationService

from tests.helpers import make_env


class _FakeCloseBroker:
    name = "fake_close"

    def __init__(self, close: BrokerClose | None, *, positions: list | None = None,
                 has_positions: bool = False) -> None:
        self.close = close
        self.calls = 0
        self._positions = positions or []
        self._has_positions = has_positions

    def closed_position(self, intent, broker_order=None):
        self.calls += 1
        return self.close

    def positions(self):
        if not self._has_positions:
            raise AttributeError("positions")
        return list(self._positions)


def _open_trade(platform, *, tenant: str = "default", side: Side = Side.BUY,
                volume: str = "0.10", status: OrderStatus = OrderStatus.FILLED,
                suffix: str = "1", risk_decision_id: str = "",
                age_hours: int = 2) -> OrderIntent:
    now = platform.clock()
    intent = OrderIntent(
        intent_id=f"oi_test_{suffix}",
        client_order_id=f"client-{suffix}",
        risk_decision_id=risk_decision_id,
        instrument_id="EURUSD",
        side=side,
        order_type=OrderType.MARKET,
        volume=Decimal(volume),
        stop_loss=Decimal("1.08000"),
        take_profit=Decimal("1.10000"),
        created_at=now - timedelta(hours=age_hours),
        status=status,
        phase=Phase.DEMO,
        tenant_id=tenant,
    )
    platform.orders.save_intent(intent)
    broker_order = BrokerOrder(
        broker_order_id=f"bo_test_{suffix}", intent_id=intent.intent_id,
        status=status, symbol="EURUSD", requested_volume=intent.volume,
        filled_volume=Decimal(volume), average_price=Decimal("1.09000"), updated_at=now,
    )
    platform.orders.save_broker_order(broker_order)
    platform.orders.save_fill(Fill(
        fill_id=stable_id("fill", intent.intent_id, length=20),
        broker_order_id=broker_order.broker_order_id,
        volume=Decimal(volume), price=Decimal("1.09000"),
        commission=Decimal("-0.7"), filled_at=intent.created_at,
    ))
    return intent


def _close(platform, *, volume: str = "0.10", gross: str = "12.5",
           commission: str = "-1.2", swap: str = "-0.3") -> BrokerClose:
    return BrokerClose(
        position_id="555001",
        symbol="EURUSD",
        volume=Decimal(volume),
        entry_price=Decimal("1.09000"),
        exit_price=Decimal("1.09500"),
        gross_profit=Decimal(gross),
        commission=Decimal(commission),
        swap=Decimal(swap),
        closed_at=platform.clock(),
        deal_ids=("900001", "900002"),
    )


def _service(platform, broker) -> CloseReconciliationService:
    return CloseReconciliationService(
        orders=platform.orders, trades=platform.closed_trades, analyses=platform.analyses,
        scenarios=platform.scenarios, decisions=platform.decisions, candles=platform.candles,
        audit=platform.audit, outbox=platform.outbox, broker=broker, clock=platform.clock,
    )


class CloseReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=300)
        self.platform = self.env.platform

    def tearDown(self) -> None:
        self.env.close()

    def test_records_real_close_and_transitions_intent(self) -> None:
        intent = _open_trade(self.platform)
        broker = _FakeCloseBroker(_close(self.platform))
        results = _service(self.platform, broker).reconcile_all(tenant_id="default")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].reason, "recorded")
        stored = self.platform.orders.get_intent(intent.intent_id)
        self.assertEqual(stored.status, OrderStatus.CLOSED)
        trade = self.platform.closed_trades.find_by_intent(intent.intent_id)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.net_profit, Decimal("11.0"))
        self.assertEqual(trade.outcome, "WIN")
        self.assertEqual(trade.volume, Decimal("0.10"))
        self.assertEqual(trade.exit_price, Decimal("1.09500"))
        self.assertEqual(trade.broker_position_id, "555001")
        self.assertEqual(trade.broker_deal_ids, ("900001", "900002"))
        actions = self.platform.db.query(
            "SELECT action FROM audit_events WHERE action='TRADE_CLOSED'")
        self.assertEqual(len(actions), 1)
        events = self.platform.db.query(
            "SELECT event_type FROM outbox WHERE event_type='execution.trade.closed'")
        self.assertEqual(len(events), 1)

    def test_is_idempotent_on_repeat(self) -> None:
        intent = _open_trade(self.platform)
        broker = _FakeCloseBroker(_close(self.platform))
        service = _service(self.platform, broker)
        service.reconcile_all(tenant_id="default")
        second = service.reconcile_all(tenant_id="default")
        self.assertEqual(second, [])
        count = self.platform.db.scalar("SELECT COUNT(*) FROM closed_trades")
        self.assertEqual(count, 1)
        # intent دیگر در فهرست بازها نیست؛ دوباره بررسی مستقیم هم رکورد تکراری نمی‌سازد
        result = service.reconcile_one(self.platform.orders.get_intent(intent.intent_id))
        self.assertEqual(result.reason, "already_recorded")
        self.assertEqual(self.platform.db.scalar("SELECT COUNT(*) FROM closed_trades"), 1)

    def test_partial_close_keeps_intent_open(self) -> None:
        intent = _open_trade(self.platform)
        broker = _FakeCloseBroker(_close(self.platform, volume="0.05"))
        results = _service(self.platform, broker).reconcile_all(tenant_id="default")
        self.assertEqual(len(results), 1)
        self.assertEqual(self.platform.orders.get_intent(intent.intent_id).status, OrderStatus.FILLED)
        trade = self.platform.closed_trades.find_by_intent(intent.intent_id)
        self.assertEqual(trade.volume, Decimal("0.05"))

    def test_partially_filled_intent_is_promoted_then_closed(self) -> None:
        intent = _open_trade(self.platform, status=OrderStatus.PARTIALLY_FILLED)
        broker = _FakeCloseBroker(_close(self.platform))
        _service(self.platform, broker).reconcile_all(tenant_id="default")
        self.assertEqual(self.platform.orders.get_intent(intent.intent_id).status, OrderStatus.CLOSED)

    def test_missing_history_marks_reconciliation_required(self) -> None:
        intent = _open_trade(self.platform)
        broker = _FakeCloseBroker(None, positions=[], has_positions=True)
        results = _service(self.platform, broker).reconcile_all(tenant_id="default")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].reason, "broker_history_unavailable")
        self.assertEqual(self.platform.orders.get_intent(intent.intent_id).status,
                         OrderStatus.RECONCILIATION_REQUIRED)
        self.assertIsNone(self.platform.closed_trades.find_by_intent(intent.intent_id))

    def test_open_position_is_not_marked_missing(self) -> None:
        intent = _open_trade(self.platform)
        broker = _FakeCloseBroker(
            None, positions=[{"ticket": 555001, "symbol": "EURUSD", "type": 0}],
            has_positions=True,
        )
        results = _service(self.platform, broker).reconcile_all(tenant_id="default")
        self.assertEqual(results, [])
        self.assertEqual(self.platform.orders.get_intent(intent.intent_id).status, OrderStatus.FILLED)

    def test_recent_intent_waits_before_marking_missing(self) -> None:
        intent = _open_trade(self.platform, age_hours=0)
        broker = _FakeCloseBroker(None, positions=[], has_positions=True)
        results = _service(self.platform, broker).reconcile_all(tenant_id="default")
        self.assertEqual(results, [])
        self.assertEqual(self.platform.orders.get_intent(intent.intent_id).status, OrderStatus.FILLED)

    def test_no_broker_support_is_safe_noop(self) -> None:
        intent = _open_trade(self.platform)
        self.platform.close_reconciliation.broker = None
        results = self.platform.close_reconciliation.reconcile_all(tenant_id="default")
        self.assertEqual(results, [])
        self.assertEqual(self.platform.orders.get_intent(intent.intent_id).status, OrderStatus.FILLED)

    def test_tenant_isolation(self) -> None:
        _open_trade(self.platform, tenant="tenant-a", suffix="a")
        _open_trade(self.platform, tenant="tenant-b", suffix="b")
        service = _service(self.platform, _FakeCloseBroker(_close(self.platform)))
        results = service.reconcile_all(tenant_id="tenant-a")
        self.assertEqual(len(results), 1)
        self.assertEqual(len(self.platform.closed_trades.list(tenant_id="tenant-a")), 1)
        self.assertEqual(len(self.platform.closed_trades.list(tenant_id="tenant-b")), 0)

    def test_r_multiple_uses_risk_amount(self) -> None:
        now = self.platform.clock()
        decision = RiskDecision(
            decision_id="rd_test", scenario_id="sc_missing", instrument_id="EURUSD",
            account_snapshot_id="acc", approved=True, risk_amount=Decimal("50"),
            risk_currency="USD", position_size=Decimal("0.10"), entry_price=Decimal("1.09"),
            stop_loss=Decimal("1.08"), take_profit=None, checks=(), policy_version="v1",
            reason_code="APPROVED", reason_detail="", valid_until=now + timedelta(hours=1),
            created_at=now, inputs_hash="h",
        )
        self.platform.decisions.save(decision)
        _open_trade(self.platform, risk_decision_id="rd_test")
        broker = _FakeCloseBroker(_close(self.platform))
        _service(self.platform, broker).reconcile_all(tenant_id="default")
        trade = self.platform.closed_trades.find_by_intent("oi_test_1")
        self.assertIsNotNone(trade)
        self.assertEqual(trade.r_multiple, Decimal("11.0") / Decimal("50"))


class AttributionTests(unittest.TestCase):
    @staticmethod
    def _trade(index: int, net: str, *, regime: str = "TRENDING_UP",
               modules: tuple[str, ...] = ("trend.ema_structure",)) -> ClosedTrade:
        from datetime import UTC, datetime

        moment = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)
        return ClosedTrade(
            trade_id=f"ct_{index}", intent_id=f"oi_{index}", tenant_id="default",
            instrument_id="EURUSD" if index % 2 == 0 else "GBPUSD", side=Side.BUY,
            volume=Decimal("0.10"), entry_price=Decimal("1.09"), exit_price=Decimal("1.10"),
            opened_at=moment, closed_at=moment + timedelta(hours=1),
            gross_profit=Decimal(net), commission=Decimal("0"), swap=Decimal("0"),
            net_profit=Decimal(net), risk_amount=Decimal("100"),
            r_multiple=Decimal(net) / Decimal("100"), regime=regime,
            timeframe="H1", supporting_modules=modules,
        )

    def test_summary_metrics(self) -> None:
        summary = summarize([self._trade(1, "20"), self._trade(2, "-10"), self._trade(3, "10")])
        self.assertEqual(summary["trades"], 3)
        self.assertEqual(summary["wins"], 2)
        self.assertEqual(summary["losses"], 1)
        self.assertEqual(summary["net_profit"], "20")
        self.assertAlmostEqual(summary["win_rate"], 0.666667, places=6)
        self.assertEqual(summary["profit_factor"], "3")
        self.assertAlmostEqual(float(summary["expectancy"]), 6.666667, places=5)
        self.assertAlmostEqual(float(summary["average_r"]), 0.066667, places=5)

    def test_group_by_module_counts_supporting_modules(self) -> None:
        trades = [
            self._trade(1, "20", modules=("trend.ema_structure", "momentum.rsi_roc")),
            self._trade(2, "-10", modules=("trend.ema_structure",)),
        ]
        rows = group_by(trades, "module")
        by_key = {row["key"]: row for row in rows}
        self.assertEqual(by_key["trend.ema_structure"]["trades"], 2)
        self.assertEqual(by_key["momentum.rsi_roc"]["trades"], 1)
        self.assertEqual(by_key["trend.ema_structure"]["net_profit"], "10")

    def test_report_is_tenant_scoped(self) -> None:
        env = make_env(bars=100)
        try:
            for index, tenant in ((1, "a"), (2, "b")):
                trade = self._trade(index, "20")
                object.__setattr__(trade, "tenant_id", tenant)
                env.platform.closed_trades.save(trade)
            report = env.platform.attribution.report("a")
            self.assertEqual(report["trade_count"], 1)
            self.assertEqual(report["summary"]["net_profit"], "20")
            self.assertEqual(len(env.platform.closed_trades.list(tenant_id="b")), 1)
        finally:
            env.close()


class DashboardPerformanceTests(unittest.TestCase):
    def test_dashboard_exposes_performance_tab(self) -> None:
        from fxars.ui.dashboard import DASHBOARD_HTML

        for marker in (
            'data-tab="performance"',
            'data-panel="performance"',
            "/api/v1/trading/attribution",
            "/api/v1/trading/closed-trades",
            "function loadPerformance",
            "function renderAttribution",
            "function renderClosedTrades",
            "checks_failed",
            "reason_detail",
        ):
            self.assertIn(marker, DASHBOARD_HTML)


if __name__ == "__main__":
    unittest.main()
