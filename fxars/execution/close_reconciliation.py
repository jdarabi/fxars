"""تطبیق معاملات بسته‌شده با تاریخچه واقعی بروکر و ثبت نتیجه/Attribution.

قواعد ایمنی:
* فقط از closing dealهای بروکر استفاده می‌شود؛ قیمت بسته‌شدن ساختگی نیست.
* اگر بروکر در دسترس نباشد یا deal خروج پیدا نشود، هیچ تغییری اعمال نمی‌شود.
* هر intent حداکثر یک ردیف ClosedTrade دارد (idempotent بر اساس intent_id).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fxars.audit.audit import AuditLog
from fxars.audit.outbox import EventType, Outbox
from fxars.core.errors import NotFoundError
from fxars.core.ids import stable_id
from fxars.core.numerics import ZERO
from fxars.domain.enums import OrderStatus, Side, Timeframe
from fxars.domain.models import BrokerOrder, ClosedTrade, OrderIntent
from fxars.execution.state_machine import transition
from fxars.storage.repositories import (
    AnalysisRepository,
    CandleRepository,
    ClosedTradeRepository,
    OrderRepository,
    RiskRepository,
    ScenarioRepository,
)

_VOLUME_TOLERANCE = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class BrokerClose:
    """خروجی یکسان‌شده تاریخچه بروکر برای یک پوزیشن بسته‌شده."""

    position_id: str
    symbol: str
    volume: Decimal
    entry_price: Decimal | None
    exit_price: Decimal | None
    gross_profit: Decimal
    commission: Decimal
    swap: Decimal
    closed_at: datetime
    deal_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CloseResult:
    intent_id: str
    trade_id: str
    from_status: OrderStatus
    to_status: OrderStatus
    closed_volume: Decimal
    net_profit: Decimal
    reason: str


class CloseReconciliationService:
    def __init__(
        self,
        *,
        orders: OrderRepository,
        trades: ClosedTradeRepository,
        analyses: AnalysisRepository,
        scenarios: ScenarioRepository,
        decisions: RiskRepository,
        candles: CandleRepository,
        audit: AuditLog,
        outbox: Outbox,
        broker: Any,
        clock,
    ) -> None:
        self.orders = orders
        self.trades = trades
        self.analyses = analyses
        self.scenarios = scenarios
        self.decisions = decisions
        self.candles = candles
        self.audit = audit
        self.outbox = outbox
        self.broker = broker
        self.clock = clock

    def reconcile_all(self, *, tenant_id: str = "default", actor: str = "system",
                      limit: int = 200) -> list[CloseResult]:
        closer = getattr(self.broker, "closed_position", None)
        if self.broker is None or not callable(closer):
            return []
        open_positions = self._open_positions()
        results: list[CloseResult] = []
        for intent in self.orders.list_open_intents(tenant_id, limit=limit):
            try:
                result = self.reconcile_one(intent, actor=actor, open_positions=open_positions)
            except Exception as exc:  # یک intent معیوب نباید کل چرخه را متوقف کند
                results.append(CloseResult(
                    intent_id=intent.intent_id, trade_id="", from_status=intent.status,
                    to_status=intent.status, closed_volume=ZERO, net_profit=ZERO,
                    reason=f"error:{type(exc).__name__}:{exc}",
                ))
                continue
            if result is not None:
                results.append(result)
        return results

    def reconcile_one(self, intent: OrderIntent, *, actor: str = "system",
                      open_positions: list | None = None) -> CloseResult | None:
        broker_order = self.orders.latest_broker_order(intent.intent_id)
        close = self.broker.closed_position(intent, broker_order)
        if close is None or close.volume <= ZERO:
            if self._missing_at_broker(intent, open_positions):
                updated = transition(intent, OrderStatus.RECONCILIATION_REQUIRED)
                with self.orders.db.transaction():
                    self.orders.save_intent(updated)
                    self.audit.append(
                        "RECONCILIATION_REQUIRED", "order_intent", intent.intent_id, actor=actor,
                        payload={
                            "reason": "broker_history_unavailable",
                            "broker_position_found": False,
                            "detail": "بروکر پوزیشن باز ندارد و تاریخچه بسته‌شدن در دسترس نیست؛ نتیجه ساختگی ثبت نشد.",
                        },
                    )
                    self.outbox.emit(
                        EventType.ORDER_INTENT_CREATED,
                        {"intent_id": intent.intent_id, "status": OrderStatus.RECONCILIATION_REQUIRED.value},
                        occurred_at=self.clock(),
                    )
                return CloseResult(
                    intent_id=intent.intent_id, trade_id="",
                    from_status=intent.status, to_status=OrderStatus.RECONCILIATION_REQUIRED,
                    closed_volume=ZERO, net_profit=ZERO, reason="broker_history_unavailable",
                )
            return None

        existing = self.trades.find_by_intent(intent.intent_id)
        if existing is not None and existing.volume == close.volume and existing.net_profit == (
            close.gross_profit + close.commission + close.swap
        ):
            return CloseResult(
                intent_id=intent.intent_id, trade_id=existing.trade_id,
                from_status=intent.status, to_status=intent.status,
                closed_volume=existing.volume, net_profit=existing.net_profit,
                reason="already_recorded",
            )

        trade = self._build_trade(intent, close, broker_order)
        filled = self._filled_volume(intent, broker_order, close.volume)
        fully_closed = close.volume + self._tolerance(filled) >= filled
        updated = self._close_status(intent) if fully_closed else intent

        with self.orders.db.transaction():
            self.trades.save(trade)
            if updated is not intent:
                self.orders.save_intent(updated)
            self.audit.append(
                "TRADE_CLOSED", "order_intent", intent.intent_id, actor=actor,
                payload={
                    "trade_id": trade.trade_id,
                    "status": updated.status.value,
                    "closed_volume": format(close.volume, "f"),
                    "net_profit": format(trade.net_profit, "f"),
                    "position_id": close.position_id,
                    "deals": len(close.deal_ids),
                    "updated": existing is not None,
                },
            )
            self.outbox.emit(
                EventType.TRADE_CLOSED,
                {
                    "trade_id": trade.trade_id,
                    "intent_id": intent.intent_id,
                    "instrument_id": trade.instrument_id,
                    "side": trade.side.value,
                    "net_profit": format(trade.net_profit, "f"),
                    "r_multiple": format(trade.r_multiple, "f") if trade.r_multiple is not None else None,
                    "status": updated.status.value,
                },
                occurred_at=self.clock(),
            )
        return CloseResult(
            intent_id=intent.intent_id, trade_id=trade.trade_id,
            from_status=intent.status, to_status=updated.status,
            closed_volume=trade.volume, net_profit=trade.net_profit,
            reason="recorded" if existing is None else "updated",
        )

    # ------------------------------------------------------------------ پوزیشن گم‌شده
    def _open_positions(self) -> list | None:
        """فهرست پوزیشن‌های باز بروکر؛ None یعنی بروکر قابلیت/پاسخ معتبر ندارد."""
        positions = getattr(self.broker, "positions", None)
        if not callable(positions):
            return None
        try:
            return list(positions())
        except Exception:
            return None

    def _missing_at_broker(self, intent: OrderIntent, open_positions: list | None) -> bool:
        """اگر بروکر قطعاً پوزیشن باز ندارد و تاریخچه هم نیست، وضعیت را نامشخص می‌کنیم.

        این تابع نتیجه معامله نمی‌سازد؛ فقط از فهرست پوزیشن‌های باز خارج می‌شود.
        """
        if open_positions is None:
            return False
        if self.clock() - intent.created_at < timedelta(hours=1):
            return False
        wanted_type = 0 if intent.side is Side.BUY else 1
        for position in open_positions:
            if str(position.get("symbol", "")) != intent.instrument_id:
                continue
            if int(position.get("type", -1)) == wanted_type:
                return False
        return True

    # ------------------------------------------------------------------ ساخت رکورد
    def _build_trade(self, intent: OrderIntent, close: BrokerClose,
                     broker_order: BrokerOrder | None) -> ClosedTrade:
        fills = self.orders.list_fills(intent.intent_id)
        opened_at = min((fill.filled_at for fill in fills), default=intent.created_at)
        entry_price = close.entry_price
        if entry_price is None and fills:
            volume = sum((fill.volume for fill in fills), ZERO)
            if volume > ZERO:
                entry_price = sum((fill.price * fill.volume for fill in fills), ZERO) / volume
        if entry_price is None and broker_order is not None:
            entry_price = broker_order.average_price

        risk = self._decision(intent)
        scenario = self._scenario(risk)
        timeframe = scenario.timeframe if scenario is not None else None
        run_id = scenario.analysis_run_id if scenario is not None else None
        strategy = run_id[len("strategy:"):] if run_id and run_id.startswith("strategy:") else None
        modules, supporting = self._modules(intent, scenario)
        regime = self._regime(intent, timeframe)
        net = close.gross_profit + close.commission + close.swap
        risk_amount = risk.risk_amount if risk is not None else None
        r_multiple = None
        if risk_amount is not None and risk_amount > ZERO:
            r_multiple = net / risk_amount

        return ClosedTrade(
            trade_id=stable_id("ct", intent.intent_id, length=20),
            intent_id=intent.intent_id,
            tenant_id=intent.tenant_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            volume=close.volume,
            entry_price=entry_price,
            exit_price=close.exit_price,
            opened_at=opened_at,
            closed_at=close.closed_at,
            gross_profit=close.gross_profit,
            commission=close.commission,
            swap=close.swap,
            net_profit=net,
            risk_amount=risk_amount,
            r_multiple=r_multiple,
            scenario_id=scenario.scenario_id if scenario is not None else None,
            analysis_run_id=run_id,
            risk_decision_id=intent.risk_decision_id or None,
            timeframe=timeframe,
            strategy=strategy,
            regime=regime,
            evidence_modules=modules,
            supporting_modules=supporting,
            broker_position_id=close.position_id,
            close_source="broker_history",
            broker_deal_ids=close.deal_ids,
            recorded_at=self.clock(),
        )

    def _decision(self, intent: OrderIntent):
        if not intent.risk_decision_id:
            return None
        try:
            return self.decisions.get(intent.risk_decision_id)
        except NotFoundError:
            return None

    def _scenario(self, risk):
        if risk is None:
            return None
        try:
            return self.scenarios.get(risk.scenario_id)
        except NotFoundError:
            return None

    def _modules(self, intent: OrderIntent, scenario) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if scenario is None or not scenario.analysis_run_id or scenario.analysis_run_id.startswith("strategy:"):
            return (), ()
        try:
            evidences = self.analyses.evidence_for(scenario.analysis_run_id)
        except Exception:
            return (), ()
        wanted = set(scenario.evidence_ids)
        related = [item for item in evidences if not wanted or item.evidence_id in wanted]
        modules = tuple(sorted({item.module_id for item in related}))
        side_sign = 1 if intent.side is Side.BUY else -1
        supporting = tuple(sorted({
            item.module_id for item in related
            if item.signed_strength * side_sign > 0 and item.strength >= 0.30
        }))
        return modules, supporting

    def _regime(self, intent: OrderIntent, timeframe: str | None) -> str | None:
        if not timeframe:
            return None
        try:
            candles = self.candles.recent_until(
                intent.instrument_id, Timeframe.parse(timeframe), end=intent.created_at, limit=200,
            )
            if len(candles) < 60:
                return None
            from fxars.research.regime import classify_regimes

            labels = classify_regimes(candles)
            return labels[-1].regime if labels else None
        except Exception:
            return None

    # ------------------------------------------------------------------ وضعیت
    def _filled_volume(self, intent: OrderIntent, broker_order: BrokerOrder | None,
                       fallback: Decimal) -> Decimal:
        fills = self.orders.list_fills(intent.intent_id)
        volume = sum((fill.volume for fill in fills), ZERO)
        if volume > ZERO:
            return volume
        if broker_order is not None and broker_order.filled_volume > ZERO:
            return broker_order.filled_volume
        return fallback

    @staticmethod
    def _tolerance(volume: Decimal) -> Decimal:
        return max(_VOLUME_TOLERANCE, volume * Decimal("0.0001"))

    @staticmethod
    def _close_status(intent: OrderIntent) -> OrderIntent:
        updated = intent
        if updated.status is OrderStatus.PARTIALLY_FILLED:
            updated = transition(updated, OrderStatus.FILLED)
        if updated.status is not OrderStatus.CLOSED:
            updated = transition(updated, OrderStatus.CLOSED)
        return updated
