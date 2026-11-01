"""آداپتر بروکر کاغذی (Paper) با اجرای قطعی برای آزمون Idempotency/تطبیق."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from fxars.core.ids import stable_id
from fxars.domain.enums import OrderStatus, Side
from fxars.domain.models import BrokerOrder, Fill, OrderIntent


@dataclass
class PaperBrokerConfig:
    spread_pips: Decimal = Decimal("1.2")
    slippage_pips: Decimal = Decimal("0.2")
    partial_fill_probability: float = 0.25
    seed: int = 7


class PaperBroker:
    name = "paper"

    def __init__(self, config: PaperBrokerConfig | None = None) -> None:
        self.config = config or PaperBrokerConfig()

    def submit(self, intent: OrderIntent, *, price: Decimal, pip_size: Decimal) -> tuple[BrokerOrder, list[Fill]]:
        digest = hashlib.sha256(intent.client_order_id.encode("utf-8")).hexdigest()
        fraction = int(digest[:4], 16) / 0xFFFF
        spread = self.config.spread_pips * pip_size
        slip = self.config.slippage_pips * pip_size
        if intent.side is Side.BUY:
            fill_price = price + spread / 2 + slip
        else:
            fill_price = price - spread / 2 - slip
        fill_price = fill_price.quantize(Decimal(1).scaleb(-5))
        if fraction < self.config.partial_fill_probability and intent.volume > Decimal("0.02"):
            filled = (intent.volume * Decimal("0.5")).quantize(Decimal("0.01"))
            status = OrderStatus.PARTIALLY_FILLED
        else:
            filled = intent.volume
            status = OrderStatus.FILLED
        broker_order_id = stable_id("bo", intent.client_order_id, length=20)
        order = BrokerOrder(
            broker_order_id=broker_order_id,
            intent_id=intent.intent_id,
            status=status,
            symbol=intent.instrument_id,
            requested_volume=intent.volume,
            filled_volume=filled,
            average_price=fill_price,
            updated_at=intent.created_at,
            message="paper fill",
        )
        fill = Fill(
            fill_id=stable_id("fill", broker_order_id, filled, fill_price, length=20),
            broker_order_id=broker_order_id,
            volume=filled,
            price=fill_price,
            commission=intent.volume * Decimal("7"),
            filled_at=intent.created_at,
        )
        return order, [fill]

    def query(self, client_order_id: str) -> BrokerOrder | None:
        return None
