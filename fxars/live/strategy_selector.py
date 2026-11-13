"""انتخاب خودکار استراتژی بر اساس بک‌تست سریع روی داده واقعی MT5.

FIX-24-STRATEGY-SELECTOR:
- چند استراتژی روی داده اخیر تست می‌شود
- بهترین بر اساس امتیاز ترکیبی انتخاب می‌شود
- سیگنال فعلی از بهترین استراتژی گرفته می‌شود
- FIX-26: Decimal/float fix + _latest_signal واقعی
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fxars.analysis.structure import Swing
from fxars.core.logging_setup import get_logger
from fxars.domain.models import Candle, Instrument

logger = get_logger("live.strategy_selector")

# استراتژی‌های دستی کاربر فقط روی M5 معنا دارند (قوانین ورود بر پایه کندل ۵ دقیقه).
REQUIRED_TIMEFRAMES: dict[str, str] = {
    "EMA20/FullBody": "M5",
    "H&S/Reversal": "M5",
}

# فیلتر روند: ورودهای M5 فقط هم‌جهت با EMA50 کندل‌های بستهٔ H1 مجاز است.
TREND_TIMEFRAME = "H1"
TREND_EMA_PERIOD = 50


def trend_history_bars(entry_bars: int) -> int:
    """تعداد کندل H1 لازم برای پوشش تاریخچهٔ M5 به‌همراه گرم‌شدن EMA."""
    hours = max(1, entry_bars) // 12
    return min(5000, max(120, hours + TREND_EMA_PERIOD + 10))


# ---------------------------------------------------------------------------
# نتیجه استراتژی
# ---------------------------------------------------------------------------
@dataclass
class StrategyResult:
    name: str
    trades: int
    net_profit: float
    sharpe: float
    profit_factor: float
    max_drawdown_pct: float
    win_rate: float
    score: float
    signal: str = "NO_TRADE"
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trades": self.trades,
            "net_profit": round(self.net_profit, 2),
            "sharpe": round(self.sharpe, 3),
            "profit_factor": round(self.profit_factor, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 3),
            "win_rate": round(self.win_rate, 3),
            "score": round(self.score, 4),
            "signal": self.signal,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# امتیاز
# ---------------------------------------------------------------------------
def _score_result(r: StrategyResult) -> float:
    sharpe_norm = max(-1.0, min(3.0, r.sharpe)) / 3.0
    pf_norm = max(0.0, min(3.0, r.profit_factor)) / 3.0
    mdd_norm = 1.0 - max(0.0, min(1.0, r.max_drawdown_pct / 100.0))
    trade_bonus = 1.0 if r.trades >= 20 else r.trades / 20.0
    return 0.4 * sharpe_norm + 0.3 * pf_norm + 0.2 * mdd_norm + 0.1 * trade_bonus


# ---------------------------------------------------------------------------
# helper: تبدیل امن Decimal به float
# ---------------------------------------------------------------------------
def _f(value: Any) -> float:
    """Decimal یا هر چیز → float."""
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _range(candle: Candle) -> float:
    """range کندل به‌صورت float."""
    return _f(candle.high) - _f(candle.low)


# ---------------------------------------------------------------------------
# فیلتر روند تایم‌فریم بالاتر
# ---------------------------------------------------------------------------
def _trend_directions(
    candles: list[Candle],
    trend_candles: list[Candle],
    *,
    period: int = TREND_EMA_PERIOD,
) -> list[str | None]:
    """جهت روند هر کندل ورودی بر پایهٔ آخرین کندل بستهٔ تایم‌فریم بالاتر.

    برای هر کندل، فقط کندل‌هایی از تایم‌فریم بالاتر استفاده می‌شوند که
    ``close_time`` آن‌ها از ``open_time`` کندل ورودی بزرگ‌تر نباشد؛ بنابراین
    هیچ اطلاعات آینده‌ای وارد سیگنال نمی‌شود.
    """
    from fxars.analysis import indicators as ind

    closed = sorted(
        (c for c in trend_candles if c.is_closed),
        key=lambda c: c.open_time,
    )
    if not closed:
        return [None] * len(candles)
    closes = [_f(c.close) for c in closed]
    ema_values = ind.ema(closes, period)

    directions: list[str | None] = []
    pointer = 0
    for candle in candles:
        while pointer < len(closed) and closed[pointer].close_time <= candle.open_time:
            pointer += 1
        last = pointer - 1
        if last < 0 or ema_values[last] is None:
            directions.append(None)
        elif closes[last] > ema_values[last]:
            directions.append("UP")
        elif closes[last] < ema_values[last]:
            directions.append("DOWN")
        else:
            directions.append(None)
    return directions


def _trend_filtered(
    entry_fn: Callable[[int, list[Candle]], tuple[str, float, float, float] | None],
    directions: list[str | None],
) -> Callable[[int, list[Candle]], tuple[str, float, float, float] | None]:
    """سیگنال را فقط وقتی نگه می‌دارد که هم‌جهت با روند باشد؛ نامشخص ⇒ مسدود."""

    def filtered(i: int, cs: list[Candle]):
        signal = entry_fn(i, cs)
        if signal is None:
            return None
        direction = directions[i] if i < len(directions) else None
        if (signal[0] == "LONG" and direction == "UP") or (
            signal[0] == "SHORT" and direction == "DOWN"
        ):
            return signal
        return None

    return filtered


# ---------------------------------------------------------------------------
# شبیه‌سازی ساده
# ---------------------------------------------------------------------------
def _simulate_simple(
    candles: list[Candle],
    instrument: Instrument,
    *,
    entry_fn: Callable[[int, list[Candle]], tuple[str, float, float, float] | None],
    name: str,
) -> StrategyResult:
    """شبیه‌سازی: هر سیگنال → ورود در close، حد ضرر و هدف ثابت.

    بازده هر معامله به‌صورت مضرب R (سود تقسیم بر ریسک اولیه) محاسبه می‌شود؛
    درصد قیمت بدون نرمال‌سازی ریسک، نمادهای مختلف را غیرقابل‌مقایسه می‌کند.
    """
    equity = 10000.0
    peak = equity
    max_dd = 0.0
    trades = 0
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    returns: list[float] = []
    pip = _f(instrument.pip_size)
    risk_fraction = 0.01  # ۱٪ ریسک هر معامله

    for i in range(50, len(candles) - 1):
        sig = entry_fn(i, candles)
        if sig is None:
            continue
        signal, entry, stop, target = sig
        if i + 1 >= len(candles):
            continue
        entry_candle = candles[i + 1]
        entry_price = _f(entry_candle.open)
        risk = abs(entry_price - stop)
        if risk < 3 * pip or risk > 150 * pip:
            continue

        exit_price = None
        for j in range(i + 1, min(i + 50, len(candles))):
            c = candles[j]
            if signal == "LONG":
                if _f(c.low) <= stop:
                    exit_price = stop
                    break
                if _f(c.high) >= target:
                    exit_price = target
                    break
            else:  # SHORT
                if _f(c.high) >= stop:
                    exit_price = stop
                    break
                if _f(c.low) <= target:
                    exit_price = target
                    break
        if exit_price is None:
            exit_price = _f(candles[min(i + 49, len(candles) - 1)].close)

        pnl = (exit_price - entry_price) if signal == "LONG" else (entry_price - exit_price)
        r_multiple = pnl / risk
        returns.append(r_multiple)
        equity *= (1 + r_multiple * risk_fraction)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)
        trades += 1
        if r_multiple > 0:
            wins += 1
            gross_profit += r_multiple
        else:
            gross_loss += abs(r_multiple)

    if trades == 0:
        return StrategyResult(
            name=name, trades=0, net_profit=0, sharpe=0, profit_factor=0,
            max_drawdown_pct=0, win_rate=0, score=0, signal="NO_TRADE",
            reason="no_trades",
        )

    net = equity - 10000.0
    avg_ret = sum(returns) / len(returns)
    var = sum((r - avg_ret) ** 2 for r in returns) / len(returns) if len(returns) > 1 else 0
    std = var ** 0.5
    sharpe = (avg_ret / std * (252 ** 0.5)) if std > 0 else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0
    wr = wins / trades

    result = StrategyResult(
        name=name, trades=trades, net_profit=net, sharpe=sharpe,
        profit_factor=pf, max_drawdown_pct=max_dd, win_rate=wr,
        score=0.0, signal="NO_TRADE",
    )
    result.score = _score_result(result)
    return result


# ---------------------------------------------------------------------------
# استراتژی ۱: SMC (Structure)
# ---------------------------------------------------------------------------
def _strategy_structure(candles: list[Candle], instrument: Instrument) -> StrategyResult:
    from fxars.analysis.structure import find_swings

    swings = find_swings(candles, 3)

    def entry_fn(i: int, cs: list[Candle]):
        recent = [s for s in swings if s.confirmed_index <= i]
        if len(recent) < 2:
            return None
        highs = [s for s in recent if s.kind == "HIGH"]
        lows = [s for s in recent if s.kind == "LOW"]
        if not highs or not lows:
            return None
        last_high = _f(highs[-1].price)
        last_low = _f(lows[-1].price)
        close = _f(cs[i].close)
        atr = _range(cs[i])
        pip = _f(instrument.pip_size)

        if close > last_high and (close - last_high) < atr * 2:
            entry = close
            stop = last_low - pip * 5
            risk = entry - stop
            return ("LONG", entry, stop, entry + risk * 2)
        if close < last_low and (last_low - close) < atr * 2:
            entry = close
            stop = last_high + pip * 5
            risk = stop - entry
            return ("SHORT", entry, stop, entry - risk * 2)
        return None

    return _simulate_simple(candles, instrument, entry_fn=entry_fn, name="SMC/Structure")


# ---------------------------------------------------------------------------
# استراتژی ۲: Trend Following (EMA cross)
# ---------------------------------------------------------------------------
def _strategy_trend(candles: list[Candle], instrument: Instrument) -> StrategyResult:
    from fxars.analysis import indicators as ind
    closes = [_f(c.close) for c in candles]
    ema_fast = ind.ema(closes, 20)
    ema_slow = ind.ema(closes, 50)

    def entry_fn(i: int, cs: list[Candle]):
        if i < 50:
            return None
        f, s = ema_fast[i], ema_slow[i]
        pf, ps = ema_fast[i - 1], ema_slow[i - 1]
        if f is None or s is None or pf is None or ps is None:
            return None
        atr = _range(cs[i])
        if pf <= ps and f > s:
            entry = _f(cs[i].close)
            stop = entry - atr * 1.5
            target = entry + atr * 3
            return ("LONG", entry, stop, target)
        if pf >= ps and f < s:
            entry = _f(cs[i].close)
            stop = entry + atr * 1.5
            target = entry - atr * 3
            return ("SHORT", entry, stop, target)
        return None

    return _simulate_simple(candles, instrument, entry_fn=entry_fn, name="Trend/EMA")


# ---------------------------------------------------------------------------
# استراتژی ۳: Mean Reversion (RSI)
# ---------------------------------------------------------------------------
def _strategy_meanrev(candles: list[Candle], instrument: Instrument) -> StrategyResult:
    from fxars.analysis import indicators as ind
    closes = [_f(c.close) for c in candles]
    rsi = ind.rsi(closes, 14)

    def entry_fn(i: int, cs: list[Candle]):
        if i < 20 or rsi[i] is None:
            return None
        r = rsi[i]
        atr = _range(cs[i])
        if r < 30:
            entry = _f(cs[i].close)
            stop = entry - atr * 1.5
            target = entry + atr * 2
            return ("LONG", entry, stop, target)
        if r > 70:
            entry = _f(cs[i].close)
            stop = entry + atr * 1.5
            target = entry - atr * 2
            return ("SHORT", entry, stop, target)
        return None

    return _simulate_simple(candles, instrument, entry_fn=entry_fn, name="MeanRev/RSI")


# ---------------------------------------------------------------------------
# استراتژی ۴: Breakout (Donchian)
# ---------------------------------------------------------------------------
def _strategy_breakout(candles: list[Candle], instrument: Instrument) -> StrategyResult:
    def entry_fn(i: int, cs: list[Candle]):
        if i < 20:
            return None
        window = cs[i - 20:i]
        prior_high = max(_f(c.high) for c in window)
        prior_low = min(_f(c.low) for c in window)
        close = _f(cs[i].close)
        pip = _f(instrument.pip_size)

        if close > prior_high:
            entry = close
            stop = prior_low - pip * 5
            risk = entry - stop
            return ("LONG", entry, stop, entry + risk * 2)
        if close < prior_low:
            entry = close
            stop = prior_high + pip * 5
            risk = stop - entry
            return ("SHORT", entry, stop, entry - risk * 2)
        return None

    return _simulate_simple(candles, instrument, entry_fn=entry_fn, name="Breakout/Donchian")


# ---------------------------------------------------------------------------
# استراتژی ۵: EMA20 + کندل فول‌بادی (قانون کاربر، M5)
# ---------------------------------------------------------------------------
def _fullbody_setup(
    candle: Candle,
    ema_value: float | None,
    pip: Decimal,
    *,
    min_pips: Decimal = Decimal("10"),
    max_pips: Decimal = Decimal("20"),
) -> tuple[str, float, float, float] | None:
    """کندل بدون سایه که بدنه‌اش کاملاً بالای/زیر EMA20 است.

    بدنه باید بین ۱۰ تا ۲۰ پیپ باشد؛ حد ضرر ۲ پیپ آن‌سوی کندل و حد سود
    دو برابر بدنه است.
    """
    if ema_value is None:
        return None
    open_, high, low, close = candle.open, candle.high, candle.low, candle.close
    if high != max(open_, close) or low != min(open_, close):
        return None  # سایه دارد؛ «فول‌بادی» نیست
    body = abs(close - open_)
    body_pips = body / pip
    if body_pips < min_pips or body_pips > max_pips:
        return None
    if close > open_ and float(open_) > ema_value:
        return (
            "LONG",
            float(close),
            float(low - 2 * pip),
            float(close + 2 * body),
        )
    if close < open_ and float(open_) < ema_value:
        return (
            "SHORT",
            float(close),
            float(high + 2 * pip),
            float(close - 2 * body),
        )
    return None


def _ema_fullbody_entry_fn(candles: list[Candle], instrument: Instrument) -> Callable:
    from fxars.analysis import indicators as ind

    closes = [_f(c.close) for c in candles]
    ema20 = ind.ema(closes, 20)
    pip = instrument.pip_size

    def entry_fn(i: int, cs: list[Candle]):
        if i >= len(ema20):
            return None
        return _fullbody_setup(cs[i], ema20[i], pip)

    return entry_fn


def _strategy_ema_fullbody(
    candles: list[Candle],
    instrument: Instrument,
    *,
    trend: list[str | None] | None = None,
) -> StrategyResult:
    entry_fn = _ema_fullbody_entry_fn(candles, instrument)
    if trend is not None:
        entry_fn = _trend_filtered(entry_fn, trend)
    return _simulate_simple(
        candles, instrument,
        entry_fn=entry_fn,
        name="EMA20/FullBody",
    )


# ---------------------------------------------------------------------------
# استراتژی ۶: سر و شانه بازگشتی (قانون کاربر، M5)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HeadShouldersSetup:
    direction: str  # LONG (سر و شانه معکوس) | SHORT (سر و شانه معمولی)
    left_price: Decimal
    kind: str


def _head_shoulders_setup(
    swings: list[Swing],
    index: int,
    *,
    max_age: int = 10,
    min_span: int = 5,
    max_span: int = 60,
) -> HeadShouldersSetup | None:
    """سه سقف/کف متوالی با ساختار شانه-سر-شانه و شانه راست در جهت موردنظر.

    معکوس (LONG): سر پایین‌تر از دو شانه و شانه راست بالاتر از شانه چپ.
    معمولی (SHORT): سر بالاتر از دو شانه و شانه راست پایین‌تر از شانه چپ.
    """
    recent = [swing for swing in swings if swing.confirmed_index <= index]
    for kind, direction in (("HIGH", "SHORT"), ("LOW", "LONG")):
        same = [swing for swing in recent if swing.kind == kind]
        if len(same) < 3:
            continue
        left, head, right = same[-3], same[-2], same[-1]
        if right.index >= index:
            continue  # کندل تریگر باید بعد از شانه راست بسته شود
        if index - right.index > max_age:
            continue
        span = right.index - left.index
        if span < min_span or span > max_span:
            continue
        if direction == "SHORT":
            if not (head.price > left.price and head.price > right.price):
                continue
            if not (right.price < left.price):
                continue
        else:
            if not (head.price < left.price and head.price < right.price):
                continue
            if not (right.price > left.price):
                continue
        # بین هر دو شانه باید یک دره/قله (نک‌لاین) وجود داشته باشد.
        middle_kind = "LOW" if kind == "HIGH" else "HIGH"
        middles = [swing for swing in recent if swing.kind == middle_kind]
        left_valley = any(left.index < swing.index < head.index for swing in middles)
        right_valley = any(head.index < swing.index < right.index for swing in middles)
        if not (left_valley and right_valley):
            continue
        return HeadShouldersSetup(direction=direction, left_price=left.price, kind=kind)
    return None


def _head_shoulders_trigger(
    setup: HeadShouldersSetup | None,
    candle: Candle,
    ema_value: float | None,
    pip: Decimal,
) -> tuple[str, float, float, float] | None:
    """کندل سبز بالای EMA20 برای خرید و کندل قرمز زیر EMA20 برای فروش.

    حد ضرر ۲ پیپ آن‌سوی شانه چپ؛ حد سود ۲۰ پیپ (برای فروش، ۲۰ پیپ زیر ورود).
    """
    if setup is None or ema_value is None:
        return None
    close = float(candle.close)
    open_ = float(candle.open)
    if setup.direction == "LONG":
        if not (close > open_ and close > ema_value):
            return None
        stop = float(setup.left_price - 2 * pip)
        return ("LONG", close, stop, float(candle.close + 20 * pip))
    if not (close < open_ and close < ema_value):
        return None
    stop = float(setup.left_price + 2 * pip)
    return ("SHORT", close, stop, float(candle.close - 20 * pip))


def _head_shoulders_entry_fn(candles: list[Candle], instrument: Instrument) -> Callable:
    from fxars.analysis import indicators as ind
    from fxars.analysis.structure import find_swings

    swings = find_swings(candles, 3)
    closes = [_f(c.close) for c in candles]
    ema20 = ind.ema(closes, 20)
    pip = instrument.pip_size

    def entry_fn(i: int, cs: list[Candle]):
        if i >= len(ema20):
            return None
        setup = _head_shoulders_setup(swings, i)
        return _head_shoulders_trigger(setup, cs[i], ema20[i], pip)

    return entry_fn


def _strategy_head_shoulders(
    candles: list[Candle],
    instrument: Instrument,
    *,
    trend: list[str | None] | None = None,
) -> StrategyResult:
    entry_fn = _head_shoulders_entry_fn(candles, instrument)
    if trend is not None:
        entry_fn = _trend_filtered(entry_fn, trend)
    return _simulate_simple(
        candles, instrument,
        entry_fn=entry_fn,
        name="H&S/Reversal",
    )


# ---------------------------------------------------------------------------
# لیست استراتژی‌ها
# ---------------------------------------------------------------------------
STRATEGIES: list[tuple[str, Callable]] = [
    ("SMC/Structure", _strategy_structure),
    ("Trend/EMA", _strategy_trend),
    ("MeanRev/RSI", _strategy_meanrev),
    ("Breakout/Donchian", _strategy_breakout),
    ("EMA20/FullBody", _strategy_ema_fullbody),
    ("H&S/Reversal", _strategy_head_shoulders),
]


def available_strategies() -> list[dict[str, str]]:
    """فهرست استراتژی‌ها برای انتخاب دستی در داشبورد/API."""
    return [
        {"name": name, "timeframe": REQUIRED_TIMEFRAMES.get(name, "")}
        for name, _ in STRATEGIES
    ]


# ---------------------------------------------------------------------------
# سیگنال فعلی (آخرین کندل)
# ---------------------------------------------------------------------------
def _latest_signal(
    strategy_name: str,
    candles: list[Candle],
    instrument: Instrument,
    *,
    trend: list[str | None] | None = None,
) -> tuple[str, float, float, float] | None:
    """آخرین سیگنال استراتژی را روی آخرین کندل می‌گیرد.

    از entry_fn همان استراتژی استفاده می‌کند.
    """
    # پیدا کردن entry_fn از استراتژی
    entry_fn = None
    for name, fn in STRATEGIES:  # noqa: B007 - fn در after-loop استفاده می‌شود
        if name != strategy_name:
            continue
        # استراتژی‌ها entry_fn داخلی دارند. اینجا از یک ترفند استفاده می‌کنیم:
        # آخرین کندل را با شبیه‌سازی یک کندل تست می‌کنیم
        # راه بهتر: entry_fn را از closure بگیریم، اما دسترسی نداریم.
        # پس از هر استراتژی، entry_fn را جدا می‌سازیم.
        break

    # بازسازی entry_fn بر اساس نام استراتژی
    if strategy_name == "SMC/Structure":
        from fxars.analysis.structure import find_swings
        swings = find_swings(candles, 3)

        def entry_fn(i, cs):
            recent = [s for s in swings if s.confirmed_index <= i]
            if len(recent) < 2:
                return None
            highs = [s for s in recent if s.kind == "HIGH"]
            lows = [s for s in recent if s.kind == "LOW"]
            if not highs or not lows:
                return None
            last_high = _f(highs[-1].price)
            last_low = _f(lows[-1].price)
            close = _f(cs[i].close)
            atr = _range(cs[i])
            pip = _f(instrument.pip_size)
            if close > last_high and (close - last_high) < atr * 2:
                entry = close
                stop = last_low - pip * 5
                return ("LONG", entry, stop, entry + (entry - stop) * 2)
            if close < last_low and (last_low - close) < atr * 2:
                entry = close
                stop = last_high + pip * 5
                return ("SHORT", entry, stop, entry - (stop - entry) * 2)
            return None

    elif strategy_name == "Trend/EMA":
        from fxars.analysis import indicators as ind
        closes = [_f(c.close) for c in candles]
        ema_fast = ind.ema(closes, 20)
        ema_slow = ind.ema(closes, 50)

        def entry_fn(i, cs):
            if i < 50:
                return None
            f, s = ema_fast[i], ema_slow[i]
            pf, ps = ema_fast[i - 1], ema_slow[i - 1]
            if f is None or s is None or pf is None or ps is None:
                return None
            atr = _range(cs[i])
            if pf <= ps and f > s:
                entry = _f(cs[i].close)
                return ("LONG", entry, entry - atr * 1.5, entry + atr * 3)
            if pf >= ps and f < s:
                entry = _f(cs[i].close)
                return ("SHORT", entry, entry + atr * 1.5, entry - atr * 3)
            return None

    elif strategy_name == "MeanRev/RSI":
        from fxars.analysis import indicators as ind
        closes = [_f(c.close) for c in candles]
        rsi = ind.rsi(closes, 14)

        def entry_fn(i, cs):
            if i < 20 or rsi[i] is None:
                return None
            r = rsi[i]
            atr = _range(cs[i])
            if r < 30:
                entry = _f(cs[i].close)
                return ("LONG", entry, entry - atr * 1.5, entry + atr * 2)
            if r > 70:
                entry = _f(cs[i].close)
                return ("SHORT", entry, entry + atr * 1.5, entry - atr * 2)
            return None

    elif strategy_name == "Breakout/Donchian":
        def entry_fn(i, cs):
            if i < 20:
                return None
            window = cs[i - 20:i]
            prior_high = max(_f(c.high) for c in window)
            prior_low = min(_f(c.low) for c in window)
            close = _f(cs[i].close)
            pip = _f(instrument.pip_size)
            if close > prior_high:
                entry = close
                stop = prior_low - pip * 5
                return ("LONG", entry, stop, entry + (entry - stop) * 2)
            if close < prior_low:
                entry = close
                stop = prior_high + pip * 5
                return ("SHORT", entry, stop, entry - (stop - entry) * 2)
            return None

    elif strategy_name == "EMA20/FullBody":
        entry_fn = _ema_fullbody_entry_fn(candles, instrument)

    elif strategy_name == "H&S/Reversal":
        entry_fn = _head_shoulders_entry_fn(candles, instrument)
    else:
        return None

    if entry_fn is None:
        return None
    if trend is not None and strategy_name in REQUIRED_TIMEFRAMES:
        entry_fn = _trend_filtered(entry_fn, trend)
    # آخرین کندل
    i = len(candles) - 1
    if i < 50:
        return None
    return entry_fn(i, candles)


# ---------------------------------------------------------------------------
# انتخاب بهترین استراتژی
# ---------------------------------------------------------------------------
def select_best_strategy(
    candles: list[Candle],
    instrument: Instrument,
    *,
    min_trades: int = 5,
    strategy: str | None = None,
    trend_candles: list[Candle] | None = None,
) -> dict[str, Any]:
    directions = (
        _trend_directions(candles, trend_candles) if trend_candles is not None else None
    )
    trend_info: dict[str, Any] = {
        "timeframe": TREND_TIMEFRAME,
        "applied": directions is not None,
        "direction": directions[-1] if directions else None,
    }
    if len(candles) < 100:
        return {
            "best": None,
            "all": [],
            "signal": "NO_TRADE",
            "reason": f"insufficient_bars ({len(candles)} < 100)",
            "available": available_strategies(),
            "selected": strategy,
            "trend_filter": trend_info,
        }

    results: list[StrategyResult] = []
    for name, fn in STRATEGIES:
        try:
            if directions is not None and name in REQUIRED_TIMEFRAMES:
                r = fn(candles, instrument, trend=directions)
            else:
                r = fn(candles, instrument)
            results.append(r)
            logger.info(
                "strategy %s: trades=%s sharpe=%.2f pf=%.2f score=%.3f",
                name, r.trades, r.sharpe, r.profit_factor, r.score,
            )
        except Exception as exc:
            logger.warning("strategy %s failed: %s", name, exc)
            results.append(StrategyResult(
                name=name, trades=0, net_profit=0, sharpe=0, profit_factor=0,
                max_drawdown_pct=0, win_rate=0, score=0, signal="NO_TRADE",
                reason=f"error: {exc}",
            ))

    chosen: StrategyResult | None = None
    selected_reason = ""
    if strategy:
        chosen = next((r for r in results if r.name == strategy), None)
        if chosen is None:
            raise ValueError(f"استراتژی ناشناخته: {strategy}")
        selected_reason = f"selected {chosen.name} by user"
    else:
        qualified = [r for r in results if r.trades >= min_trades]
        if not qualified:
            return {
                "best": None,
                "all": [r.to_dict() for r in results],
                "signal": "NO_TRADE",
                "reason": f"no_strategy_with_min_trades ({min_trades})",
                "available": available_strategies(),
                "selected": None,
                "trend_filter": trend_info,
            }
        chosen = max(qualified, key=lambda r: r.score)
        selected_reason = f"selected {chosen.name} with score {chosen.score:.3f}"

    # سیگنال فعلی
    current_signal = "NO_TRADE"
    entry = stop = target = None
    try:
        sig = _latest_signal(chosen.name, candles, instrument, trend=directions)
        if sig is not None:
            current_signal, entry, stop, target = sig
        elif directions is not None and chosen.name in REQUIRED_TIMEFRAMES:
            unfiltered = _latest_signal(chosen.name, candles, instrument)
            if unfiltered is not None:
                selected_reason += (
                    f"؛ سیگنال {unfiltered[0]} به‌دلیل ناهم‌سویی با روند "
                    f"{TREND_TIMEFRAME} رد شد."
                )
    except Exception as exc:
        logger.warning("latest signal failed: %s", exc)

    chosen.signal = current_signal
    chosen.entry = entry
    chosen.stop = stop
    chosen.target = target

    return {
        "best": chosen.to_dict(),
        "all": [r.to_dict() for r in results],
        "signal": current_signal,
        "entry": entry,
        "stop": stop,
        "target": target,
        "reason": selected_reason,
        "available": available_strategies(),
        "selected": strategy,
        "trend_filter": trend_info,
    }
