"""FIX-LIVE-01: دریافت کندل زنده از MetaTrader 5.

نکات:
* فقط روی Windows کار می‌کند (MetaTrader5 package).
* MT5 باید باز و لاگین باشد.
* روی حساب دمو تست شود — فاز READ_ONLY هیچ سفارشی نمی‌فرستد.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fxars.core.timeutil import floor_to_timeframe, timeframe_delta
from fxars.domain.models import Candle

logger = logging.getLogger('fxars.live.mt5')


class MT5UnavailableError(RuntimeError):
    """MetaTrader5 package نصب نیست یا MT5 باز نیست."""


# نگاشت timeframe نام‌ها به MT5 constant (lazy — package optional)
_TF_MAP: dict[str, str] = {
    'M1': 'TIMEFRAME_M1',
    'M5': 'TIMEFRAME_M5',
    'M15': 'TIMEFRAME_M15',
    'M30': 'TIMEFRAME_M30',
    'H1': 'TIMEFRAME_H1',
    'H4': 'TIMEFRAME_H4',
    'D1': 'TIMEFRAME_D1',
    'W1': 'TIMEFRAME_W1',
}


class MT5Feed:
    """دریافت کندل از MetaTrader 5 و تبدیل به Candle."""

    def __init__(self, *, source_id: str = 'mt5') -> None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise MT5UnavailableError(
                'MetaTrader5 package نصب نیست. pip install MetaTrader5'
            ) from exc
        self._mt5 = mt5
        self.source_id = source_id
        if not mt5.initialize():
            code, msg = mt5.last_error()
            raise MT5UnavailableError(f'MT5 initialize failed: ({code}) {msg}')
        info = mt5.account_info()
        if info is None:
            mt5.shutdown()
            raise MT5UnavailableError('MT5 account_info is None — آیا لاگین هستی؟')
        self._account = info
        logger.info(
            'MT5 connected: login=%s server=%s balance=%s %s',
            info.login, info.server, info.balance, info.currency,
        )

    def account_info(self) -> dict[str, Any]:
        info = self._account
        return {
            'login': info.login,
            'server': info.server,
            'currency': info.currency,
            'balance': float(info.balance),
            'equity': float(info.equity),
            'margin_free': float(info.margin_free),
            'leverage': info.leverage,
        }

    def symbol_info(self, symbol: str) -> dict[str, Any] | None:
        si = self._mt5.symbol_info(symbol)
        if si is None:
            return None
        return {
            'symbol': si.name,
            'digits': si.digits,
            'point': float(si.point),
            'spread': si.spread,
            'trade_contract_size': float(si.trade_contract_size),
            'min_lot': float(si.volume_min),
            'max_lot': float(si.volume_max),
            'lot_step': float(si.volume_step),
            'currency_base': si.currency_base,
            'currency_profit': si.currency_profit,
        }

    def _timeframe_constant(self, timeframe: str):
        key = _TF_MAP.get(timeframe.upper())
        if key is None:
            raise ValueError(f'timeframe پشتیبانی نمی‌شود: {timeframe!r}')
        return getattr(self._mt5, key)

    def fetch_recent(
        self, symbol: str, timeframe: str, count: int = 500,
    ) -> list[Candle]:
        """آخرین `count` کندل بسته‌شده را بگیر و به Candle تبدیل کن."""
        tf_const = self._timeframe_constant(timeframe)
        rates = self._mt5.copy_rates_from_pos(symbol, tf_const, 0, int(count))
        if rates is None or len(rates) == 0:
            code, msg = self._mt5.last_error()
            raise MT5UnavailableError(
                f'copy_rates_from_pos {symbol}/{timeframe} failed: ({code}) {msg}'
            )
        now = datetime.now(tz=timezone.utc)
        tf_delta = timeframe_delta(timeframe.upper())
        candles: list[Candle] = []
        # B7: use symbol point (supports 3-digit JPY, 2-digit XAU)
        si = self.symbol_info(symbol)
        if si is None:
            raise MT5UnavailableError(f'symbol_info({symbol}) is None')
        point = Decimal(str(si['point']))

        for r in rates:
            open_time = datetime.fromtimestamp(int(r['time']), tz=timezone.utc)
            close_time = open_time + tf_delta
            is_closed = close_time <= now
            if not is_closed:
                # آخرین کندل باز است — رد کن
                continue
            candle = Candle(
                instrument_id=symbol,
                source_id=self.source_id,
                timeframe=timeframe.upper(),
                open_time=open_time,
                open=Decimal(str(r['open'])),
                high=Decimal(str(r['high'])),
                low=Decimal(str(r['low'])),
                close=Decimal(str(r['close'])),
                tick_volume=int(r['tick_volume']) if 'tick_volume' in r.dtype.names else None,
                spread=Decimal(str(r['spread'])) * point
                    if 'spread' in r.dtype.names and r['spread'] > 0 else None,
                is_closed=True,
                available_at=close_time,
                ingested_at=now,
                quality_status='VALID',
            )
            candles.append(candle)
        candles.sort(key=lambda c: c.open_time)
        return candles

    def fetch_new(
        self, symbol: str, timeframe: str, *, since: datetime, count: int = 100,
    ) -> list[Candle]:
        """کندل‌های جدیدتر از `since` را بگیر."""
        all_candles = self.fetch_recent(symbol, timeframe, count=count)
        since = since.astimezone(timezone.utc) if since.tzinfo else since.replace(tzinfo=timezone.utc)
        return [c for c in all_candles if c.open_time > since]

    def shutdown(self) -> None:
        try:
            self._mt5.shutdown()
        except Exception:
            pass
