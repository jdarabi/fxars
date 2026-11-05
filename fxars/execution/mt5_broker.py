"""MT5Broker: send orders to MetaTrader 5 (demo account only).

Safety: only works when phase is DEMO (not READ_ONLY).
Only demo accounts allowed (server must contain 'demo' or trade_mode == 0).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from fxars.core.ids import stable_id
from fxars.core.timeutil import utcnow
from fxars.domain.enums import OrderStatus, Side
from fxars.domain.models import BrokerOrder, Fill, OrderIntent

logger = logging.getLogger("fxars.execution.mt5")


class MT5BrokerError(RuntimeError):
    """MT5 broker operation failed."""


@dataclass
class MT5Broker:
    name: str = "mt5"

    def __post_init__(self) -> None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise MT5BrokerError("MetaTrader5 package not installed") from exc
        self._mt5 = mt5
        if not mt5.initialize():
            code, msg = mt5.last_error()
            raise MT5BrokerError(f"MT5 initialize failed: ({code}) {msg}")
        info = mt5.account_info()
        if info is None:
            mt5.shutdown()
            raise MT5BrokerError("MT5 account_info is None (not logged in)")
        server_lower = info.server.lower()
        is_demo = "demo" in server_lower or "test" in server_lower or info.trade_mode == 0
        if not is_demo:
            mt5.shutdown()
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
        broker_order_id = str(result.order)
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

    def query(self, client_order_id: str) -> BrokerOrder | None:
        logger.warning("MT5Broker.query not implemented (returns None)")
        return None

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
        try:
            self._mt5.shutdown()
        except Exception:
            pass
