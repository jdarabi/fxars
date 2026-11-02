"""PaperBroker with deterministic behavior and explicit fault injection."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from fxars.core.ids import stable_id
from fxars.core.timeutil import utcnow
from fxars.domain.enums import OrderStatus, Side
from fxars.domain.models import BrokerOrder, Fill, OrderIntent


@dataclass
class PaperBrokerConfig:
    spread_pips: Decimal = Decimal("1.2")
    slippage_pips: Decimal = Decimal("0.2")
    partial_fill_probability: float = 0.25
    reject_probability: float = 0.0
    timeout_probability: float = 0.0
    seed: int = 7


@dataclass
class PaperBroker:
    """Deterministic paper broker with optional fault injection."""

    config: PaperBrokerConfig = field(default_factory=PaperBrokerConfig)
    name: str = "paper"

    def _fraction(self, client_order_id: str, salt: str = "") -> float:
        digest = hashlib.sha256(f"{client_order_id}|{salt}".encode("utf-8")).hexdigest()
        return int(digest[:8], 16) / 0xFFFFFFFF

    def submit(
        self,
        intent: OrderIntent,
        *,
        price: Decimal,
        pip_size: Decimal,
        now: datetime | None = None,
    ) -> tuple[BrokerOrder, list[Fill]]:
        moment = now or utcnow()
        fraction_fill = self._fraction(intent.client_order_id, "fill")
        fraction_reject = self._fraction(intent.client_order_id, "reject")
        fraction_timeout = self._fraction(intent.client_order_id, "timeout")

        if self.config.reject_probability > 0 and fraction_reject < self.config.reject_probability:
            return self._rejected(intent, moment, reason="injected_reject")
        if self.config.timeout_probability > 0 and fraction_timeout < self.config.timeout_probability:
            return self._unknown(intent, moment, reason="injected_timeout")

        spread = self.config.spread_pips * pip_size
        slip = self.config.slippage_pips * pip_size
        if intent.side is Side.BUY:
            fill_price = price + spread / Decimal("2") + slip
        else:
            fill_price = price - spread / Decimal("2") - slip
        fill_price = fill_price.quantize(Decimal(1).scaleb(-5))

        if fraction_fill < self.config.partial_fill_probability and intent.volume > Decimal("0.02"):
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
            updated_at=moment,
            message=f"paper fill ({status.value})",
        )
        fill = Fill(
            fill_id=stable_id("fill", broker_order_id, filled, fill_price, length=20),
            broker_order_id=broker_order_id,
            volume=filled,
            price=fill_price,
            commission=intent.volume * Decimal("7"),
            filled_at=moment,
        )
        return order, [fill]

    def query(self, client_order_id: str) -> BrokerOrder | None:
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
            message=f"paper reject: {reason}",
        )
        return order, []

    def _unknown(self, intent: OrderIntent, moment: datetime, *, reason: str) -> tuple[BrokerOrder, list[Fill]]:
        order = BrokerOrder(
            broker_order_id=stable_id("bo", intent.client_order_id, reason, length=20),
            intent_id=intent.intent_id,
            status=OrderStatus.UNKNOWN,
            symbol=intent.instrument_id,
            requested_volume=intent.volume,
            filled_volume=Decimal("0"),
            average_price=None,
            updated_at=moment,
            message=f"paper unknown: {reason}",
        )
        return order, []