"""زمینه تحلیل: سری‌های قیمتی، اندیکاتورها و دسترسی نقطه‌ای به گذشته."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property

from fxars.analysis import indicators as ind
from fxars.config.settings import AnalysisSettings
from fxars.core.numerics import to_decimal
from fxars.core.timeutil import format_ts
from fxars.domain.enums import Timeframe
from fxars.domain.models import Candle, EconomicEvent, Instrument
from fxars.instruments.calendar import TradingCalendar


@dataclass(frozen=True)
class IndicatorSet:
    ema_fast: tuple[ind.Number, ...]
    ema_slow: tuple[ind.Number, ...]
    ema_trend: tuple[ind.Number, ...]
    rsi: tuple[ind.Number, ...]
    roc: tuple[ind.Number, ...]
    atr: tuple[ind.Number, ...]
    atr_percentile: tuple[ind.Number, ...]
    real_vol_short: tuple[ind.Number, ...]
    real_vol_long: tuple[ind.Number, ...]

    @classmethod
    def build(cls, candles: Sequence[Candle], settings: AnalysisSettings) -> IndicatorSet:
        closes = [float(candle.close) for candle in candles]
        highs = [float(candle.high) for candle in candles]
        lows = [float(candle.low) for candle in candles]
        atr_series = ind.atr(highs, lows, closes, settings.atr_period)
        # صدک ATR فقط روی مقادیر معتبر گذشته محاسبه می‌شود
        atr_percentile: list[ind.Number] = [None] * len(atr_series)
        for index, value in enumerate(atr_series):
            if value is None:
                continue
            start = max(0, index - settings.atr_percentile_window + 1)
            window = [item for item in atr_series[start:index + 1] if item is not None]
            if len(window) < 10:
                continue
            atr_percentile[index] = 100.0 * sum(1 for item in window if item <= value) / len(window)
        return cls(
            ema_fast=tuple(ind.ema(closes, settings.ema_fast)),
            ema_slow=tuple(ind.ema(closes, settings.ema_slow)),
            ema_trend=tuple(ind.ema(closes, settings.ema_trend)),
            rsi=tuple(ind.rsi(closes, settings.rsi_period)),
            roc=tuple(ind.roc(closes, settings.roc_period)),
            atr=tuple(atr_series),
            atr_percentile=tuple(atr_percentile),
            real_vol_short=tuple(ind.rolling_std([r or 0.0 for r in ind.returns(closes)], settings.vol_window)),
            real_vol_long=tuple(ind.rolling_std([r or 0.0 for r in ind.returns(closes)], settings.vol_window * 4)),
        )


@dataclass(frozen=True)
class AnalysisContext:
    instrument: Instrument
    timeframe: str
    candles: list[Candle]
    as_of: datetime
    settings: AnalysisSettings
    indicators: IndicatorSet
    calendar: TradingCalendar
    economic_events: tuple[EconomicEvent, ...] = ()
    references: dict[str, list[Candle]] | None = None

    def __post_init__(self) -> None:
        if self.references is None:
            object.__setattr__(self, "references", {})

    @property
    def n(self) -> int:
        return len(self.candles)

    @property
    def tf(self) -> Timeframe:
        return Timeframe.parse(self.timeframe)

    @property
    def last_index(self) -> int:
        return len(self.candles) - 1

    @cached_property
    def opens(self) -> list[float]:
        return [float(candle.open) for candle in self.candles]

    @cached_property
    def highs(self) -> list[float]:
        return [float(candle.high) for candle in self.candles]

    @cached_property
    def lows(self) -> list[float]:
        return [float(candle.low) for candle in self.candles]

    @cached_property
    def closes(self) -> list[float]:
        return [float(candle.close) for candle in self.candles]

    def candle(self, index: int) -> Candle:
        return self.candles[index]

    def bar_ref(self, index: int) -> str:
        candle = self.candles[index]
        return f"{candle.instrument_id}:{candle.timeframe}:{format_ts(candle.open_time)}"

    def atr_pips(self, index: int, default: float = 10.0) -> float:
        value = ind.value_at(self.indicators.atr, index)
        if value is None:
            return default
        pips = float(self.instrument.pip_size)
        return max(value / pips, 0.1) if pips else default

    def price_to_pips(self, distance: float) -> float:
        return distance / float(self.instrument.pip_size)

    def pips_to_price(self, pips: float):
        return to_decimal(pips) * self.instrument.pip_size

    def expiry(self, index: int, bars: int | None = None):
        horizon = bars if bars is not None else self.settings.evidence_horizon_bars
        return self.candles[index].open_time + self.tf.delta * horizon

    def session_names(self) -> tuple[str, ...]:
        return tuple(session.value for session in self.calendar.sessions_at(self.as_of))

    def events_for_currencies(self, currencies: set[str]) -> list[EconomicEvent]:
        return [event for event in self.economic_events if event.currency in currencies]

    def reference(self, instrument_id: str) -> list[Candle]:
        return (self.references or {}).get(instrument_id, [])

    def bar_start(self, index: int) -> datetime:
        return self.candles[index].open_time

    def horizon_time(self, index: int, bars: int) -> datetime:
        return self.candles[index].open_time + self.tf.delta * bars

    def lookback_start(self, bars: int) -> datetime:
        return self.as_of - self.tf.delta * bars
