"""FIX-LIVE-08: MT5 Feed با symbol_select async-safe + broker offset."""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fxars.core.timeutil import timeframe_delta
from fxars.domain.models import Candle
from fxars.live.mt5_connection import MT5ConnectionError
from fxars.live.mt5_connection import acquire as acquire_mt5
from fxars.live.mt5_connection import release as release_mt5

logger = logging.getLogger('fxars.live.mt5')

# نمادهای ناموجود تا این مدت کش می‌شوند تا هر درخواست کل فهرست نمادها را اسکن نکند.
_SYMBOL_MISS_TTL_SECONDS = 60.0

# سرورهای MT5 معمولاً وقت GMT+2/+3 با قواعد DST اروپا دارند.
_BROKER_TZ_CANDIDATES = ("Europe/Athens", "Europe/Kyiv", "Europe/Helsinki")


class MT5UnavailableError(RuntimeError):
    pass


_TF_MAP = {
    'M1': 'TIMEFRAME_M1', 'M5': 'TIMEFRAME_M5', 'M15': 'TIMEFRAME_M15',
    'M30': 'TIMEFRAME_M30', 'H1': 'TIMEFRAME_H1', 'H4': 'TIMEFRAME_H4',
    'D1': 'TIMEFRAME_D1', 'W1': 'TIMEFRAME_W1',
}


def detect_broker_offset(mt5) -> timedelta:
    """اختلاف زمان سرور بروکر با UTC؛ زمان کندل MT5 در وقت سرور است، نه UTC."""
    try:
        rates = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_M1, 0, 2)
        if rates is None or len(rates) == 0:
            return timedelta(0)
        last_dt = datetime.fromtimestamp(int(rates[-1]['time']), tz=UTC)
        return timedelta(hours=round((last_dt - datetime.now(tz=UTC)).total_seconds() / 3600))
    except Exception:
        return timedelta(0)


def resolve_broker_timezone(offset: timedelta, broker_timezone: str | None = None) -> ZoneInfo | None:
    """منطقه‌زمانی سرور بروکر تا DST در کل بازه تاریخی درست تبدیل شود."""
    if broker_timezone:
        return ZoneInfo(broker_timezone)
    now = datetime.now(tz=UTC)
    for name in _BROKER_TZ_CANDIDATES:
        tz = ZoneInfo(name)
        if now.astimezone(tz).utcoffset() == offset:
            return tz
    return None


def server_time_to_utc(timestamp: int, *, tz: ZoneInfo | None, fallback_offset: timedelta) -> datetime:
    """زمان دیواری سرور (ثبت‌شده در rates) را به UTC واقعی تبدیل می‌کند."""
    wall = datetime.fromtimestamp(int(timestamp), tz=UTC).replace(tzinfo=None)
    if tz is not None:
        return wall.replace(tzinfo=tz).astimezone(UTC)
    return wall.replace(tzinfo=UTC) - fallback_offset


class MT5Feed:
    def __init__(self, *, source_id: str = 'mt5', broker_timezone: str | None = None) -> None:
        try:
            self._mt5 = acquire_mt5()
        except MT5ConnectionError as exc:
            raise MT5UnavailableError(str(exc)) from exc
        self.source_id = source_id
        self._closed = False
        info = self._mt5.account_info()
        if info is None:
            release_mt5()
            self._closed = True
            raise MT5UnavailableError('MT5 account_info is None')
        self._account = info
        self._symbol_cache = {}
        self._symbol_misses: dict[str, tuple[float, str]] = {}
        self._broker_offset = detect_broker_offset(self._mt5)
        self._broker_tz = resolve_broker_timezone(self._broker_offset, broker_timezone)
        logger.info(
            'MT5 connected: login=%s offset=%s tz=%s',
            info.login, self._broker_offset, self._broker_tz,
        )

    def account_info(self):
        info = self._account
        return {
            'login': info.login, 'server': info.server,
            'currency': info.currency,
            'balance': float(info.balance), 'equity': float(info.equity),
            'margin_free': float(info.margin_free), 'leverage': info.leverage,
        }

    def account_snapshot(self) -> dict[str, Any]:
        """اطلاعات جاری حساب با Decimal برای ساخت AccountSnapshot."""
        info = self._mt5.account_info()
        if info is None:
            raise MT5UnavailableError('MT5 account_info is None')
        return {
            'login': info.login,
            'server': info.server,
            'currency': str(info.currency).upper(),
            'balance': Decimal(str(info.balance)),
            'equity': Decimal(str(info.equity)),
            'margin_free': Decimal(str(info.margin_free)),
            'margin_used': Decimal(str(info.margin)),
            'leverage': Decimal(str(info.leverage)),
        }

    def open_positions(self) -> list[dict[str, Any]]:
        raw = self._mt5.positions_get() or ()
        positions: list[dict[str, Any]] = []
        for item in raw:
            positions.append({
                'ticket': str(item.ticket),
                'symbol': str(item.symbol),
                'type': int(item.type),
                'volume': Decimal(str(item.volume)),
                'price_open': Decimal(str(item.price_open)),
                'price_current': Decimal(str(item.price_current)),
                'sl': Decimal(str(item.sl)) if item.sl else None,
                'tp': Decimal(str(item.tp)) if item.tp else None,
                'commission': Decimal(str(getattr(item, 'commission', 0) or 0)),
                'swap': Decimal(str(getattr(item, 'swap', 0) or 0)),
            })
        return positions

    def tick(self, symbol: str) -> dict[str, Decimal] | None:
        resolved = self._resolve_symbol(symbol)
        raw = self._mt5.symbol_info_tick(resolved)
        if raw is None or raw.bid <= 0 or raw.ask <= 0:
            return None
        return {'bid': Decimal(str(raw.bid)), 'ask': Decimal(str(raw.ask))}

    def select_symbol(self, symbol: str) -> str | None:
        """فعال‌سازی نماد و بازگرداندن نام واقعی بروکر؛ None در صورت شکست."""
        try:
            resolved = self._resolve_symbol(symbol)
            self._ensure_selected(resolved)
            return resolved
        except MT5UnavailableError:
            return None

    def realized_pnl_since(self, start: datetime) -> Decimal:
        """سود/زیان محقق‌شده معاملات از start تا اکنون (شامل کمیسیون و سواپ)."""
        end = datetime.now(tz=UTC) + timedelta(minutes=5)
        deals = self._mt5.history_deals_get(start, end)
        if not deals:
            return Decimal('0')
        trade_types = {
            int(getattr(self._mt5, 'DEAL_TYPE_BUY', 0)),
            int(getattr(self._mt5, 'DEAL_TYPE_SELL', 1)),
        }
        total = Decimal('0')
        for deal in deals:
            if int(deal.type) not in trade_types:
                continue
            total += Decimal(str(deal.profit)) + Decimal(str(deal.commission)) + Decimal(str(deal.swap))
        return total

    def _resolve_symbol(self, symbol):
        cached = self._symbol_cache.get(symbol)
        if cached:
            return cached
        miss = self._symbol_misses.get(symbol)
        if miss is not None:
            expires_at, message = miss
            if time.monotonic() < expires_at:
                raise MT5UnavailableError(message)
            self._symbol_misses.pop(symbol, None)
        if self._mt5.symbol_info(symbol) is not None:
            self._symbol_cache[symbol] = symbol
            return symbol
        if self._mt5.symbol_select(symbol, True):
            for _attempt in range(10):
                if self._mt5.symbol_info(symbol) is not None:
                    self._symbol_cache[symbol] = symbol
                    return symbol
                time.sleep(0.2)
        prefix = symbol.upper()
        candidates = []
        for s in self._mt5.symbols_get() or []:
            name = s.name
            upper = name.upper()
            if upper == prefix:
                candidates.insert(0, name)
            elif upper.startswith(prefix) and len(name) <= len(prefix) + 4:
                candidates.append(name)
        if not candidates:
            raise self._symbol_miss(symbol, f'نماد {symbol!r} در بروکر یافت نشد')
        resolved = candidates[0]
        if self._mt5.symbol_select(resolved, True):
            for _attempt in range(10):
                if self._mt5.symbol_info(resolved) is not None:
                    self._symbol_cache[symbol] = resolved
                    return resolved
                time.sleep(0.2)
        raise self._symbol_miss(symbol, f'نتوانستم {symbol} را فعال کنم')

    def _symbol_miss(self, symbol: str, message: str) -> MT5UnavailableError:
        """خطای نماد را برای مدت کوتاه کش می‌کند و همان خطا را برمی‌گرداند."""
        self._symbol_misses[symbol] = (time.monotonic() + _SYMBOL_MISS_TTL_SECONDS, message)
        return MT5UnavailableError(message)

    def _ensure_selected(self, symbol):
        if not self._mt5.symbol_select(symbol, True):
            code, msg = self._mt5.last_error()
            raise MT5UnavailableError(f'symbol_select({symbol}) failed: ({code}) {msg}')
        for _ in range(10):
            if self._mt5.symbol_info(symbol) is not None:
                return
            time.sleep(0.2)
        raise MT5UnavailableError(f'symbol_info({symbol}) still None')

    def symbol_info(self, symbol):
        resolved = self._resolve_symbol(symbol)
        si = self._mt5.symbol_info(resolved)
        if si is None:
            return None
        return {
            'symbol': si.name, 'digits': si.digits,
            'point': float(si.point), 'spread': si.spread,
            'trade_contract_size': float(si.trade_contract_size),
            'min_lot': float(si.volume_min), 'max_lot': float(si.volume_max),
            'lot_step': float(si.volume_step),
            'currency_base': si.currency_base, 'currency_profit': si.currency_profit,
        }

    def _timeframe_constant(self, timeframe):
        key = _TF_MAP.get(timeframe.upper())
        if key is None:
            raise ValueError(f'timeframe پشتیبانی نمی‌شود: {timeframe!r}')
        return getattr(self._mt5, key)

    def fetch_recent(self, symbol, timeframe, count=500):
        resolved = self._resolve_symbol(symbol)
        self._ensure_selected(resolved)
        tf_const = self._timeframe_constant(timeframe)
        rates = self._mt5.copy_rates_from_pos(resolved, tf_const, 0, int(count))
        if rates is None or len(rates) == 0:
            code, msg = self._mt5.last_error()
            raise MT5UnavailableError(f'copy_rates_from_pos {resolved} failed: ({code}) {msg}')
        now = datetime.now(tz=UTC)
        tf_delta = timeframe_delta(timeframe.upper())
        si = self.symbol_info(resolved)
        if si is None:
            raise MT5UnavailableError(f'symbol_info({resolved}) is None')
        point = Decimal(str(si['point']))
        candles = []
        for r in rates:
            open_time = server_time_to_utc(
                int(r['time']), tz=self._broker_tz, fallback_offset=self._broker_offset,
            )
            close_time = open_time + tf_delta
            if close_time > now:
                continue
            candle = Candle(
                instrument_id=symbol, source_id=self.source_id,
                timeframe=timeframe.upper(), open_time=open_time,
                open=Decimal(str(r['open'])), high=Decimal(str(r['high'])),
                low=Decimal(str(r['low'])), close=Decimal(str(r['close'])),
                tick_volume=int(r['tick_volume']) if 'tick_volume' in r.dtype.names else None,
                spread=Decimal(str(r['spread'])) * point if 'spread' in r.dtype.names and r['spread'] > 0 else None,
                is_closed=True, available_at=close_time, ingested_at=now,
                quality_status='VALID',
            )
            candles.append(candle)
        candles.sort(key=lambda c: c.open_time)
        return candles

    def fetch_new(self, symbol, timeframe, *, since, count=100):
        all_candles = self.fetch_recent(symbol, timeframe, count=count)
        since = since.astimezone(UTC) if since.tzinfo else since.replace(tzinfo=UTC)
        return [c for c in all_candles if c.open_time > since]

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        release_mt5()
