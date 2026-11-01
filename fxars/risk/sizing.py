"""محاسبه اندازه موقعیت با Decimal و مشخصات قراردادی نماد (بخش ۹-۱)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fxars.core.numerics import ZERO, floor_to_step, quantize, to_decimal
from fxars.domain.models import Instrument


@dataclass(frozen=True)
class SizingInput:
    equity: Decimal
    risk_fraction: Decimal
    entry_price: Decimal
    stop_price: Decimal
    instrument: Instrument
    quote_to_account_rate: Decimal = Decimal("1")
    commission_per_lot: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("equity", "risk_fraction", "entry_price", "stop_price", "quote_to_account_rate"):
            object.__setattr__(self, name, to_decimal(getattr(self, name), field=name))


@dataclass(frozen=True)
class SizingResult:
    valid: bool
    reason: str
    risk_amount: Decimal
    stop_distance: Decimal
    stop_pips: Decimal
    pip_value_per_lot: Decimal
    loss_per_lot: Decimal
    raw_volume: Decimal
    volume: Decimal
    estimated_loss_at_stop: Decimal
    rounding_loss: Decimal

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "reason": self.reason,
            "risk_amount": format(self.risk_amount, "f"),
            "stop_distance": format(self.stop_distance, "f"),
            "stop_pips": format(quantize(self.stop_pips, 2), "f"),
            "pip_value_per_lot": format(quantize(self.pip_value_per_lot, 2), "f"),
            "loss_per_lot": format(quantize(self.loss_per_lot, 2), "f"),
            "raw_volume": format(quantize(self.raw_volume, 4), "f"),
            "volume": format(self.volume, "f"),
            "estimated_loss_at_stop": format(quantize(self.estimated_loss_at_stop, 2), "f"),
            "rounding_loss": format(quantize(self.rounding_loss, 2), "f"),
        }


def calculate_position_size(data: SizingInput) -> SizingResult:
    instrument = data.instrument
    risk_amount = data.equity * data.risk_fraction
    stop_distance = abs(data.entry_price - data.stop_price)
    if stop_distance <= ZERO:
        return _invalid("STOP_DISTANCE_ZERO", risk_amount, stop_distance)

    stop_pips = stop_distance / instrument.pip_size
    # ارزش یک لات در یک پیپ، بر حسب ارز حساب
    pip_value_per_lot = instrument.pip_size * instrument.contract_size * data.quote_to_account_rate
    commission = data.commission_per_lot if data.commission_per_lot is not None else instrument.commission_per_lot
    loss_per_lot = stop_pips * pip_value_per_lot + commission
    if loss_per_lot <= ZERO:
        return _invalid("LOSS_PER_LOT_INVALID", risk_amount, stop_distance)

    raw_volume = risk_amount / loss_per_lot
    capped = min(raw_volume, instrument.max_lot)
    volume = floor_to_step(capped, instrument.lot_step)
    if volume < instrument.min_lot:
        return SizingResult(
            valid=False,
            reason="BELOW_MIN_LOT",
            risk_amount=quantize(risk_amount, 2),
            stop_distance=stop_distance,
            stop_pips=stop_pips,
            pip_value_per_lot=pip_value_per_lot,
            loss_per_lot=loss_per_lot,
            raw_volume=raw_volume,
            volume=ZERO,
            estimated_loss_at_stop=ZERO,
            rounding_loss=raw_volume * loss_per_lot,
        )

    estimated_loss = volume * loss_per_lot
    return SizingResult(
        valid=True,
        reason="OK",
        risk_amount=quantize(risk_amount, 2),
        stop_distance=stop_distance,
        stop_pips=stop_pips,
        pip_value_per_lot=pip_value_per_lot,
        loss_per_lot=loss_per_lot,
        raw_volume=raw_volume,
        volume=volume,
        estimated_loss_at_stop=quantize(estimated_loss, 2),
        rounding_loss=quantize(raw_volume * loss_per_lot - estimated_loss, 2),
    )


def _invalid(reason: str, risk_amount: Decimal, stop_distance: Decimal) -> SizingResult:
    return SizingResult(
        valid=False, reason=reason, risk_amount=quantize(risk_amount, 2), stop_distance=stop_distance,
        stop_pips=ZERO, pip_value_per_lot=ZERO, loss_per_lot=ZERO, raw_volume=ZERO, volume=ZERO,
        estimated_loss_at_stop=ZERO, rounding_loss=ZERO,
    )
