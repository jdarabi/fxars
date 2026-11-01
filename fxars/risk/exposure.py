"""مواجهه ارزی و همبستگی (محافظه‌کارانه بر مبنای مارجین)."""

from __future__ import annotations

from decimal import Decimal

from fxars.core.numerics import ZERO, to_decimal
from fxars.domain.models import Instrument, Position


def margin_required(instrument: Instrument, volume: Decimal, price: Decimal, quote_to_account_rate: Decimal) -> Decimal:
    notional_quote = volume * instrument.contract_size * price
    notional_account = notional_quote * quote_to_account_rate
    return notional_account * instrument.margin_rate


def position_margin(position: Position, instrument: Instrument, quote_to_account_rate: Decimal) -> Decimal:
    return margin_required(instrument, position.volume, position.current_price, quote_to_account_rate)


def currency_exposures(
    positions: list[Position],
    instruments: dict[str, Instrument],
    rates: dict[str, Decimal],
) -> dict[str, Decimal]:
    exposures: dict[str, Decimal] = {}
    for position in positions:
        instrument = instruments.get(position.instrument_id)
        if instrument is None:
            continue
        rate = _rate(instrument, rates)
        margin = position_margin(position, instrument, rate)
        sign = 1 if position.side.value == "BUY" else -1
        exposures[instrument.base_currency] = exposures.get(instrument.base_currency, ZERO) + margin * sign
        exposures[instrument.quote_currency] = exposures.get(instrument.quote_currency, ZERO) - margin * sign
    return exposures


def candidate_exposures(
    instrument: Instrument,
    volume: Decimal,
    price: Decimal,
    side: str,
    rates: dict[str, Decimal],
) -> dict[str, Decimal]:
    rate = _rate(instrument, rates)
    margin = margin_required(instrument, volume, price, rate)
    sign = 1 if side.upper() == "BUY" else -1
    return {instrument.base_currency: margin * sign, instrument.quote_currency: -margin * sign}


def combined_currency_ok(
    positions: list[Position],
    instruments: dict[str, Instrument],
    rates: dict[str, Decimal],
    instrument: Instrument,
    volume: Decimal,
    price: Decimal,
    side: str,
    limit: Decimal,
) -> tuple[bool, dict[str, Decimal]]:
    exposures = currency_exposures(positions, instruments, rates)
    for currency, amount in candidate_exposures(instrument, volume, price, side, rates).items():
        exposures[currency] = exposures.get(currency, ZERO) + amount
    worst = max((abs(value) for value in exposures.values()), default=ZERO)
    return worst <= limit, exposures


def correlated_margin(
    positions: list[Position],
    instruments: dict[str, Instrument],
    rates: dict[str, Decimal],
    correlations: dict[str, float],
    threshold: float,
) -> Decimal:
    total = ZERO
    for position in positions:
        instrument = instruments.get(position.instrument_id)
        if instrument is None:
            continue
        correlation = abs(correlations.get(position.instrument_id, 0.0))
        if correlation >= threshold:
            total += position_margin(position, instrument, _rate(instrument, rates))
    return total


def _rate(instrument: Instrument, rates: dict[str, Decimal]) -> Decimal:
    if instrument.quote_currency.upper() == "USD":
        return Decimal("1")
    return to_decimal(rates.get(instrument.quote_currency, "1"))
