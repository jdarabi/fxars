"""مشخصات قراردادی نمادها (Instrument Spec) و نمادهای پیش‌فرض دمو."""

from __future__ import annotations

from decimal import Decimal

from fxars.domain.models import Instrument


def _inst(
    instrument_id: str,
    base: str,
    quote: str,
    digits: int,
    point: str,
    pip: str,
    contract: str,
    tick_size: str,
    tick_value: str,
    margin_rate: str,
    min_lot: str = "0.01",
    lot_step: str = "0.01",
    max_lot: str = "100",
    swap_long: str = "-2.5",
    swap_short: str = "-0.8",
    commission: str = "7.0",
    stop_level: int = 0,
    freeze_level: int = 0,
) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        symbol=instrument_id,
        base_currency=base,
        quote_currency=quote,
        digits=digits,
        point=Decimal(point),
        pip_size=Decimal(pip),
        contract_size=Decimal(contract),
        min_lot=Decimal(min_lot),
        lot_step=Decimal(lot_step),
        max_lot=Decimal(max_lot),
        tick_size=Decimal(tick_size),
        tick_value=Decimal(tick_value),
        profit_currency=quote,
        margin_rate=Decimal(margin_rate),
        stop_level_points=stop_level,
        freeze_level_points=freeze_level,
        swap_long=Decimal(swap_long),
        swap_short=Decimal(swap_short),
        commission_per_lot=Decimal(commission),
        version=1,
        source="seed",
    )


def default_instruments() -> list[Instrument]:
    """۱۰ نماد پرکاربرد فارکس/طلا + DXY به‌عنوان سری مرجع بین‌بازاری.

    مقادیر قراردادی (swap/commission/margin_rate) نمونه و قابل بازنویسی‌اند؛
    برای معامله واقعی باید از مشخصات بروکر گرفته شوند.

    الگوی digits/point/pip:
      * جفت‌های ۵ رقمی (EURUSD, GBPUSD, AUDUSD, USDCAD, USDCHF, NZDUSD):
        digits=5, point=0.00001, pip=0.0001
      * جفت‌های ۳ رقمی JPY (USDJPY, EURJPY, GBPJPY):
        digits=3, point=0.001, pip=0.01
      * XAUUSD (طلا):
        digits=2, point=0.01, pip=0.1
    """
    return [
        # ---------------------------------------------------------- Major (6)
        _inst(
            "EURUSD", "EUR", "USD", 5, "0.00001", "0.0001", "100000",
            "0.00001", "1.0", "0.01",
        ),
        _inst(
            "GBPUSD", "GBP", "USD", 5, "0.00001", "0.0001", "100000",
            "0.00001", "1.0", "0.01",
            swap_long="-2.9", swap_short="-0.6",
        ),
        _inst(
            "USDJPY", "USD", "JPY", 3, "0.001", "0.01", "100000",
            "0.001", "0.67", "0.01",
            swap_long="-3.4", swap_short="0.9",
        ),
        _inst(
            "AUDUSD", "AUD", "USD", 5, "0.00001", "0.0001", "100000",
            "0.00001", "1.0", "0.01",
            swap_long="-1.9", swap_short="-1.1",
        ),
        _inst(
            "USDCAD", "USD", "CAD", 5, "0.00001", "0.0001", "100000",
            "0.00001", "0.73", "0.01",
            swap_long="-2.4", swap_short="-0.4",
        ),
        _inst(
            "USDCHF", "USD", "CHF", 5, "0.00001", "0.0001", "100000",
            "0.00001", "1.25", "0.01",
            swap_long="-2.2", swap_short="-0.9",
        ),
        # ---------------------------------------------------------- Minors/Cross (2)
        _inst(
            "NZDUSD", "NZD", "USD", 5, "0.00001", "0.0001", "100000",
            "0.00001", "0.62", "0.01",
            swap_long="-1.6", swap_short="-1.2",
        ),
        _inst(
            "EURJPY", "EUR", "JPY", 3, "0.001", "0.01", "100000",
            "0.001", "0.67", "0.01",
            swap_long="-3.1", swap_short="0.4",
        ),
        _inst(
            "GBPJPY", "GBP", "JPY", 3, "0.001", "0.01", "100000",
            "0.001", "0.67", "0.01",
            swap_long="-4.1", swap_short="0.6",
        ),
        # ---------------------------------------------------------- Metal (1)
        _inst(
            "XAUUSD", "XAU", "USD", 2, "0.01", "0.1", "100",
            "0.01", "1.0", "0.02",
            min_lot="0.01", max_lot="50",
            swap_long="-6.5", swap_short="-1.5", commission="5.0",
        ),
        # ---------------------------------------------------------- Reference (non-tradable)
        _inst(
            "DXY", "USDX", "USD", 3, "0.001", "0.01", "1000",
            "0.001", "1.0", "1.0",
            min_lot="0.01", max_lot="0.01",
            swap_long="0", swap_short="0", commission="0",
        ),
    ]


DEFAULT_SOURCE = {
    "source_id": "demo_feed",
    "name": "Demo Synthetic Feed",
    "kind": "synthetic",
    "license_id": "internal-demo",
    "redistribution_allowed": False,
    "retention_days": 3650,
    "timezone": "UTC",
    "priority": 10,
    "notes": "داده شبیه‌سازی‌شده برای دمو/آزمون؛ نماینده بازار واقعی نیست.",
}


def is_reference_instrument(instrument_id: str) -> bool:
    return instrument_id.upper().endswith("DXY") or instrument_id.upper().startswith("REF_")
