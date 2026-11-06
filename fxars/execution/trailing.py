"""Trailing stop-loss logic for MT5 positions.

این ماژول بین `consult.py` و `daemon.py` مشترک است. تنها یک تعریف از
`apply_trailing_sl` وجود دارد تا از باگ قبلی (دو تعریف در consult.py که
دومی اولی را override می‌کرد) جلوگیری شود.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("fxars.execution.trailing")


def _buffer_points(digits: int, trailing_pips: int) -> int:
    """محاسبه buffer بر حسب point بر اساس digits نماد."""
    if digits == 3:  # JPY pairs
        return trailing_pips
    if digits == 2:  # XAU
        return trailing_pips * 10
    return trailing_pips * 10  # 5-digit forex


def _new_sl_for_position(p: Any, trailing_pips: int) -> tuple[float, str]:
    """محاسبه SL جدید برای یک پوزیشن. برمی‌گرداند (new_sl, side_label)."""
    si = p.symbol_info if hasattr(p, "symbol_info") else None
    digits = si.digits if si is not None else 5
    point = si.point if si is not None else 0.00001
    buffer_points = _buffer_points(digits, trailing_pips)

    current = p.price_current
    entry = p.price_open

    if p.type == 1:  # SELL
        new_sl = current + point * buffer_points
        if new_sl > entry:
            new_sl = entry
        return float(new_sl), "SELL"
    else:  # BUY
        new_sl = current - point * buffer_points
        if new_sl < entry:
            new_sl = entry
        return float(new_sl), "BUY"


def apply_trailing_sl(
    *,
    trailing_pips: int = 40,
    mt5: Any | None = None,
    logger_: logging.Logger | None = None,
) -> int:
    """اعمال trailing stop-loss روی همه پوزیشن‌های باز. برمی‌گرداند تعداد به‌روزشده."""
    log = logger_ or logger

    if mt5 is None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError:
            log.warning("MetaTrader5 not installed; trailing skipped")
            return 0

    try:
        positions = mt5.positions_get()
    except Exception as exc:
        log.error("positions_get failed: %s", exc)
        return 0

    if not positions:
        return 0

    updated = 0
    for p in positions:
        try:
            si = mt5.symbol_info(p.symbol)
            if si is None:
                continue
            p.symbol_info = si

            new_sl, side = _new_sl_for_position(p, trailing_pips)

            if p.type == 1:  # SELL
                if p.sl > 0 and new_sl >= p.sl:
                    continue
            else:  # BUY
                if p.sl > 0 and new_sl <= p.sl:
                    continue

            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": p.ticket,
                "symbol": p.symbol,
                "sl": float(new_sl),
                "tp": float(p.tp),
            }
            result = mt5.order_send(request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                updated += 1
                log.info("trailing %s: SL -> %s", p.symbol, new_sl)
        except Exception as exc:
            log.error("trailing error for %s: %s", getattr(p, "symbol", "?"), exc)

    return updated
