"""MT5Broker: send orders to MetaTrader 5 (demo account only).

Safety: only works when phase is DEMO (not READ_ONLY).
Only demo accounts allowed (server must contain 'demo' or trade_mode == 0).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fxars.core.ids import stable_id
from fxars.core.timeutil import utcnow
from fxars.domain.enums import OrderStatus, Side
from fxars.domain.models import BrokerOrder, Fill, OrderIntent
from fxars.live.mt5_connection import MT5ConnectionError
from fxars.live.mt5_connection import acquire as acquire_mt5
from fxars.live.mt5_connection import release as release_mt5

logger = logging.getLogger("fxars.execution.mt5")

# MT5 محدودیت ۳۱ کاراکتری برای comment دارد؛ شناسه کلاینت در همین طول ذخیره می‌شود
# تا reconciliation بتواند سفارش را در history پیدا کند.
CLIENT_COMMENT_LIMIT = 31
HISTORY_LOOKBACK_DAYS = 30

_STATE_TO_STATUS: dict[int, OrderStatus] = {
    2: OrderStatus.CANCELED,       # ORDER_STATE_CANCELED
    3: OrderStatus.PARTIALLY_FILLED,
    4: OrderStatus.FILLED,
    5: OrderStatus.REJECTED,
    6: OrderStatus.CANCELED,       # ORDER_STATE_EXPIRED
}


class MT5BrokerError(RuntimeError):
    """MT5 broker operation failed."""


def _epoch_to_utc(value: int | float | None) -> datetime:
    if not value:
        return utcnow()
    return datetime.fromtimestamp(float(value), tz=UTC)


@dataclass
class MT5Broker:
    name: str = "mt5"

    def __post_init__(self) -> None:
        try:
            self._mt5 = acquire_mt5()
        except MT5ConnectionError as exc:
            raise MT5BrokerError(str(exc)) from exc
        info = self._mt5.account_info()
        if info is None:
            release_mt5()
            raise MT5BrokerError("MT5 account_info is None (not logged in)")
        server_lower = info.server.lower()
        is_demo = "demo" in server_lower or "test" in server_lower or info.trade_mode == 0
        if not is_demo:
            release_mt5()
            raise MT5BrokerError(
                f"REFUSING: not a demo account (server={info.server}, trade_mode={info.trade_mode}). "
                "Switch to demo account first."
            )
        logger.info("MT5Broker connected: login=%s server=%s balance=%s",
                    info.login, info.server, info.balance)

    def submit(
        self,
        intent: OrderIntent,
        *,
        price: Decimal,
        pip_size: Decimal,
        now: datetime | None = None,
    ) -> tuple[BrokerOrder, list[Fill]]:
        moment = now or utcnow()
        order_type = self._mt5.ORDER_TYPE_BUY if intent.side is Side.BUY else self._mt5.ORDER_TYPE_SELL
        symbol = intent.instrument_id

        si = self._mt5.symbol_info(symbol)
        if si is None:
            return self._rejected(intent, moment, reason=f"symbol {symbol} not found")
        if not si.visible:
            self._mt5.symbol_select(symbol, True)
            si = self._mt5.symbol_info(symbol)

        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            return self._rejected(intent, moment, reason=f"no tick for {symbol}")

        fill_price = tick.ask if intent.side is Side.BUY else tick.bid

        volume = float(intent.volume)
        if volume < si.volume_min:
            return self._rejected(intent, moment, reason=f"volume {volume} < min {si.volume_min}")
        if volume > si.volume_max:
            volume = si.volume_max
        step = si.volume_step
        volume = round(volume / step) * step

        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": float(fill_price),
            "deviation": 20,
            "magic": 20261106,
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_FOK,
        }
        if intent.stop_loss:
            request["sl"] = float(intent.stop_loss)
        if intent.take_profit:
            request["tp"] = float(intent.take_profit)

        logger.info("MT5 order_send: %s", request)
        result = self._mt5.order_send(request)

        if result is None:
            code, msg = self._mt5.last_error()
            return self._rejected(intent, moment, reason=f"order_send None: ({code}) {msg}")

        if result.retcode != self._mt5.TRADE_RETCODE_DONE:
            return self._rejected(
                intent, moment,
                reason=f"retcode={result.retcode} comment={result.comment}",
            )

        filled_volume = Decimal(str(result.volume))
        fill_price = Decimal(str(result.price))
        # FIX-LIVE-16: اگر order و deal صفر هستند از intent_id استفاده کن
        broker_order_id = (
            str(result.order) if result.order
            else (f"deal_{result.deal}" if getattr(result, "deal", 0) else f"intent_{intent.intent_id}")
        )
        fill_id = stable_id("fill", broker_order_id, filled_volume, fill_price, length=20)

        broker_order = BrokerOrder(
            broker_order_id=broker_order_id,
            intent_id=intent.intent_id,
            status=OrderStatus.FILLED,
            symbol=symbol,
            requested_volume=intent.volume,
            filled_volume=filled_volume,
            average_price=fill_price,
            updated_at=moment,
            message=f"MT5 filled (retcode={result.retcode})",
        )
        fill = Fill(
            fill_id=fill_id,
            broker_order_id=broker_order_id,
            volume=filled_volume,
            price=fill_price,
            commission=Decimal("0"),
            filled_at=moment,
        )
        return broker_order, [fill]

    # ------------------------------------------------------------------
    # بازیابی سفارش از history بروکر برای reconciliation
    # ------------------------------------------------------------------
    def query(self, client_order_id: str) -> BrokerOrder | None:
        details = self.query_details(client_order_id)
        return details[0] if details is not None else None

    def query_intent(self, intent: OrderIntent) -> tuple[BrokerOrder, list[Fill]] | None:
        """بازیابی سفارش UNKNOWN بر اساس مشخصات intent (بدون نیاز به comment)."""
        history = getattr(self._mt5, "history_orders_get", None)
        if history is None:
            return None
        order = self._find_history_order_for_intent(intent)
        if order is None:
            return None
        return self._build_from_history(order, intent.intent_id)

    def query_details(self, client_order_id: str) -> tuple[BrokerOrder, list[Fill]] | None:
        """جستجوی سفارش با comment (یا تیکت عددی) و ساخت BrokerOrder/Fill از history."""
        history = getattr(self._mt5, "history_orders_get", None)
        if history is None:
            return None
        order = self._find_history_order(client_order_id)
        if order is None:
            return None
        return self._build_from_history(order, client_order_id)

    def _build_from_history(self, order, intent_id: str) -> tuple[BrokerOrder, list[Fill]]:
        ticket = int(getattr(order, "ticket", 0) or 0)
        requested = Decimal(str(getattr(order, "volume_initial", 0) or 0))
        remaining = Decimal(str(getattr(order, "volume_current", 0) or 0))
        state = int(getattr(order, "state", -1))
        status = _STATE_TO_STATUS.get(state, OrderStatus.UNKNOWN)
        if status is OrderStatus.FILLED and not remaining:
            remaining = Decimal("0")
        filled = requested - remaining if requested >= remaining else Decimal("0")
        price_raw = getattr(order, "price_current", 0) or getattr(order, "price_open", 0)
        average = Decimal(str(price_raw)) if price_raw else None
        moment = _epoch_to_utc(getattr(order, "time_done", 0) or getattr(order, "time_setup", 0))

        broker_order = BrokerOrder(
            broker_order_id=str(ticket) if ticket else intent_id,
            intent_id=intent_id,
            status=status,
            symbol=str(getattr(order, "symbol", "")),
            requested_volume=requested,
            filled_volume=filled,
            average_price=average,
            updated_at=moment,
            message=f"MT5 history state={state}",
        )
        return broker_order, self._fills_for_order(ticket, since=moment - timedelta(days=1))

    def _find_history_order_for_intent(self, intent: OrderIntent):
        """سفارش را با magic + نماد + حجم + جهت در بازه زمانی intent پیدا می‌کند."""
        history = getattr(self._mt5, "history_orders_get", None)
        if history is None:
            return None
        start = intent.created_at - timedelta(minutes=2)
        end = utcnow() + timedelta(minutes=5)
        try:
            orders = history(start, end)
        except Exception:
            logger.exception("MT5 history_orders_get failed")
            return None
        expected_type = self._mt5.ORDER_TYPE_BUY if intent.side is Side.BUY else self._mt5.ORDER_TYPE_SELL
        wanted_volume = float(intent.volume)
        matches = []
        for order in orders or ():
            if str(getattr(order, "symbol", "")) != intent.instrument_id:
                continue
            if int(getattr(order, "type", -1)) != expected_type:
                continue
            if int(getattr(order, "magic", 0) or 0) != 20261106:
                continue
            volume = float(getattr(order, "volume_initial", 0) or 0)
            if abs(volume - wanted_volume) > 1e-9:
                continue
            matches.append(order)
        if not matches:
            return None
        return min(matches, key=lambda o: getattr(o, "time_setup", 0) or 0)

    def _find_history_order(self, client_order_id: str):
        history = getattr(self._mt5, "history_orders_get", None)
        if history is None:
            return None
        if client_order_id.isdigit():
            try:
                found = history(ticket=int(client_order_id))
            except Exception:
                found = None
            if found:
                return found[0]
        comment = client_order_id[:CLIENT_COMMENT_LIMIT]
        now = utcnow()
        try:
            orders = history(now - timedelta(days=HISTORY_LOOKBACK_DAYS), now + timedelta(minutes=5))
        except Exception:
            logger.exception("MT5 history_orders_get failed")
            return None
        for order in orders or ():
            if str(getattr(order, "comment", "")) == comment:
                return order
        return None

    def _fills_for_order(self, ticket: int, *, since: datetime | None = None) -> list[Fill]:
        deals_get = getattr(self._mt5, "history_deals_get", None)
        if ticket <= 0 or deals_get is None:
            return []
        moment = utcnow()
        start = (since or moment - timedelta(days=HISTORY_LOOKBACK_DAYS))
        try:
            deals = deals_get(start, moment + timedelta(minutes=5))
        except Exception:
            logger.exception("MT5 history_deals_get failed")
            return []
        fills: list[Fill] = []
        for deal in deals or ():
            if int(getattr(deal, "order", 0) or 0) != ticket:
                continue
            volume = Decimal(str(getattr(deal, "volume", 0) or 0))
            price = Decimal(str(getattr(deal, "price", 0) or 0))
            if volume <= 0 or price <= 0:
                continue
            fills.append(Fill(
                fill_id=stable_id("fill", ticket, getattr(deal, "ticket", ""), length=20),
                broker_order_id=str(ticket),
                volume=volume,
                price=price,
                commission=Decimal(str(getattr(deal, "commission", 0) or 0)),
                filled_at=_epoch_to_utc(getattr(deal, "time", 0)),
            ))
        return fills

    # ------------------------------------------------------------------
    # تاریخچه بسته‌شدن پوزیشن (برای ثبت نتیجه واقعی)
    # ------------------------------------------------------------------
    def closed_position(self, intent: OrderIntent,
                        broker_order: BrokerOrder | None = None):
        """اگر پوزیشن این intent کاملاً/جزئاً بسته شده باشد، BrokerClose برمی‌گرداند."""
        from fxars.execution.close_reconciliation import BrokerClose

        deals_get = getattr(self._mt5, "history_deals_get", None)
        if deals_get is None:
            return None
        end = utcnow() + timedelta(minutes=5)
        start = intent.created_at - timedelta(minutes=5)
        try:
            deals = list(deals_get(start, end) or ())
        except Exception:
            logger.exception("MT5 history_deals_get failed")
            return None

        position_ids = self._position_ids_for_intent(intent, broker_order, deals)
        if not position_ids:
            return None
        owned = [deal for deal in deals
                 if int(getattr(deal, "position_id", 0) or 0) in position_ids]
        closes = [deal for deal in owned if int(getattr(deal, "entry", -1)) in (1, 2)]
        if not closes:
            return None
        opens = [deal for deal in owned if int(getattr(deal, "entry", -1)) in (0, 2)]

        closed_volume = sum((Decimal(str(getattr(deal, "volume", 0) or 0)) for deal in closes), Decimal("0"))
        if closed_volume <= 0:
            return None
        exit_price = self._weighted_price(closes)
        entry_price = self._weighted_price(opens)
        if entry_price is None and broker_order is not None:
            entry_price = broker_order.average_price
        gross = sum((Decimal(str(getattr(deal, "profit", 0) or 0)) for deal in closes), Decimal("0"))
        commission = sum((Decimal(str(getattr(deal, "commission", 0) or 0)) for deal in owned), Decimal("0"))
        swap = sum((Decimal(str(getattr(deal, "swap", 0) or 0)) for deal in owned), Decimal("0"))
        closed_at = max(_epoch_to_utc(getattr(deal, "time", 0)) for deal in closes)

        return BrokerClose(
            position_id=",".join(str(item) for item in sorted(position_ids)),
            symbol=intent.instrument_id,
            volume=closed_volume,
            entry_price=entry_price,
            exit_price=exit_price,
            gross_profit=gross,
            commission=commission,
            swap=swap,
            closed_at=closed_at,
            deal_ids=tuple(str(getattr(deal, "ticket", "")) for deal in sorted(
                owned, key=lambda item: int(getattr(item, "time", 0) or 0))),
        )

    def _position_ids_for_intent(self, intent: OrderIntent, broker_order: BrokerOrder | None,
                                 deals: list) -> set[int]:
        """شناسه پوزیشن را از تیکت سفارش/معامله پیدا می‌کند؛ بدون حدس کورکورانه."""
        ids: set[int] = set()
        ticket = 0
        if broker_order is not None and str(broker_order.broker_order_id).isdigit():
            ticket = int(broker_order.broker_order_id)
        if ticket > 0:
            history = getattr(self._mt5, "history_orders_get", None)
            if history is not None:
                try:
                    found = history(ticket=ticket) or ()
                except Exception:
                    found = ()
                for order in found:
                    position_id = int(getattr(order, "position_id", 0) or 0)
                    if position_id:
                        ids.add(position_id)
            for deal in deals:
                if int(getattr(deal, "order", 0) or 0) != ticket:
                    continue
                if int(getattr(deal, "entry", -1)) not in (0, 2):
                    continue
                position_id = int(getattr(deal, "position_id", 0) or 0)
                if position_id:
                    ids.add(position_id)
        if ids:
            return ids

        # fallback فقط برای سفارش‌هایی که تیکت معتبر ندارند (magic + نماد + جهت + حجم + زمان)
        wanted_type = 0 if intent.side is Side.BUY else 1
        tolerance = max(Decimal("0.000001"), intent.volume * Decimal("0.01"))
        best: tuple[float, int] | None = None
        moment = intent.created_at.timestamp()
        for deal in deals:
            if str(getattr(deal, "symbol", "")) != intent.instrument_id:
                continue
            if int(getattr(deal, "magic", 0) or 0) != 20261106:
                continue
            if int(getattr(deal, "type", -1)) != wanted_type:
                continue
            if int(getattr(deal, "entry", -1)) not in (0, 2):
                continue
            volume = Decimal(str(getattr(deal, "volume", 0) or 0))
            if abs(volume - intent.volume) > tolerance:
                continue
            distance = abs(float(getattr(deal, "time", 0) or 0) - moment)
            if distance > 900:
                continue
            position_id = int(getattr(deal, "position_id", 0) or 0)
            if not position_id:
                continue
            if best is None or distance < best[0]:
                best = (distance, position_id)
        return {best[1]} if best is not None else set()

    @staticmethod
    def _weighted_price(deals: list) -> Decimal | None:
        volume = sum((Decimal(str(getattr(deal, "volume", 0) or 0)) for deal in deals), Decimal("0"))
        if volume <= 0:
            return None
        total = sum((Decimal(str(getattr(deal, "price", 0) or 0))
                     * Decimal(str(getattr(deal, "volume", 0) or 0)) for deal in deals), Decimal("0"))
        return total / volume

    # ------------------------------------------------------------------
    # پوزیشن‌ها، بستن و لغو
    # ------------------------------------------------------------------
    def positions(self, symbol: str | None = None) -> list[dict]:
        positions_get = getattr(self._mt5, "positions_get", None)
        if positions_get is None:
            return []
        raw = positions_get(symbol=symbol) if symbol else positions_get()
        return [
            {
                "ticket": int(item.ticket),
                "symbol": str(item.symbol),
                "type": int(item.type),
                "volume": Decimal(str(item.volume)),
                "price_open": Decimal(str(item.price_open)),
                "price_current": Decimal(str(item.price_current)),
                "profit": Decimal(str(getattr(item, "profit", 0) or 0)),
            }
            for item in raw or ()
        ]

    def close_position(
        self, position_ticket: int, *, volume: float | None = None, now: datetime | None = None,
    ) -> tuple[BrokerOrder, list[Fill]]:
        """بستن (کامل یا جزئی) یک پوزیشن با سفارش بازار معکوس."""
        moment = now or utcnow()
        positions_get = getattr(self._mt5, "positions_get", None)
        position = None
        if positions_get is not None:
            for item in positions_get(ticket=int(position_ticket)) or ():
                position = item
                break
        if position is None:
            raise MT5BrokerError(f"position {position_ticket} not found")

        symbol = str(position.symbol)
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5BrokerError(f"no tick for {symbol}")
        closing_buy = int(position.type) != self._mt5.ORDER_TYPE_BUY
        price = tick.ask if closing_buy else tick.bid
        close_volume = float(volume if volume is not None else position.volume)

        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": close_volume,
            "type": self._mt5.ORDER_TYPE_BUY if closing_buy else self._mt5.ORDER_TYPE_SELL,
            "position": int(position_ticket),
            "price": float(price),
            "deviation": 20,
            "magic": 20261106,
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_FOK,
            "comment": "fxars-close",
        }
        result = self._mt5.order_send(request)
        if result is None:
            code, msg = self._mt5.last_error()
            raise MT5BrokerError(f"close order_send None: ({code}) {msg}")
        if result.retcode != self._mt5.TRADE_RETCODE_DONE:
            raise MT5BrokerError(
                f"close retcode={result.retcode} comment={result.comment}",
            )
        ticket = str(result.order) if result.order else f"close_{position_ticket}"
        filled = Decimal(str(result.volume))
        fill_price = Decimal(str(result.price))
        broker_order = BrokerOrder(
            broker_order_id=ticket, intent_id=f"close-{position_ticket}",
            status=OrderStatus.FILLED, symbol=symbol,
            requested_volume=Decimal(str(close_volume)),
            filled_volume=filled, average_price=fill_price, updated_at=moment,
            message="MT5 position closed",
        )
        fill = Fill(
            fill_id=stable_id("fill", ticket, filled, fill_price, length=20),
            broker_order_id=ticket, volume=filled, price=fill_price,
            commission=Decimal("0"), filled_at=moment,
        )
        return broker_order, [fill]

    def cancel_order(self, broker_order_id: int | str) -> bool:
        """لغو سفارش معلق؛ True یعنی بروکر لغو را پذیرفت."""
        request = {
            "action": self._mt5.TRADE_ACTION_REMOVE,
            "order": int(broker_order_id),
        }
        result = self._mt5.order_send(request)
        if result is None:
            return False
        return result.retcode == self._mt5.TRADE_RETCODE_DONE

    def _rejected(self, intent: OrderIntent, moment: datetime, *, reason: str) -> tuple[BrokerOrder, list[Fill]]:
        order = BrokerOrder(
            broker_order_id=stable_id("bo", intent.client_order_id, reason, length=20),
            intent_id=intent.intent_id,
            status=OrderStatus.REJECTED,
            symbol=intent.instrument_id,
            requested_volume=intent.volume,
            filled_volume=Decimal("0"),
            average_price=None,
            updated_at=moment,
            message=f"MT5 reject: {reason}",
        )
        logger.warning("MT5 order rejected: %s", reason)
        return order, []

    def shutdown(self) -> None:
        release_mt5()
