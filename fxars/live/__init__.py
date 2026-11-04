"""FX-ARS Live: دستیار real-time با MT5 + Telegram.

FIX-LIVE-01: دریافت کندل زنده از MetaTrader 5.
FIX-LIVE-02: ارسال هشدار به Telegram.
FIX-LIVE-03: daemon حلقه اصلی.
"""
from fxars.live.mt5_feed import MT5Feed, MT5UnavailableError

__all__ = ['MT5Feed', 'MT5UnavailableError']
