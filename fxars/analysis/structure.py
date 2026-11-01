"""ساختار بازار: Swing، BOS/CHoCH، FVG، Order Block، Liquidity Sweep، Displacement.

تعریف‌های عملیاتی و نسخه‌دار مطابق بخش ۷-۲ سند. هر یافته با زمان مشاهده و زمان
دسترس‌پذیری ثبت می‌شود تا در بک‌تست، نگاه به آینده رخ ندهد.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from fxars.analysis import indicators as ind
from fxars.analysis.context import AnalysisContext
from fxars.analysis.evidence import EvidenceFactory
from fxars.core.numerics import clamp
from fxars.core.timeutil import format_ts
from fxars.domain.enums import Direction, EvidenceFamily
from fxars.domain.models import Candle, Evidence, PriceZone

MODULE_VERSION = "1.0.0"


@dataclass(frozen=True)
class Swing:
    index: int
    price: Decimal
    kind: str  # HIGH | LOW
    confirmed_index: int

    @property
    def confirmed_at(self) -> int:
        return self.confirmed_index


@dataclass(frozen=True)
class BreakEvent:
    kind: str  # BOS_UP | BOS_DOWN | CHOCH_UP | CHOCH_DOWN
    index: int
    level: Decimal
    swing: Swing
    trend_before: str

    @property
    def direction_name(self) -> str:
        return "LONG" if self.kind.endswith("_UP") else "SHORT"


@dataclass(frozen=True)
class FVG:
    index: int
    direction: Direction
    zone: PriceZone


@dataclass(frozen=True)
class OrderBlock:
    index: int
    direction: Direction
    zone: PriceZone
    displacement_ratio: float


@dataclass(frozen=True)
class Sweep:
    index: int
    direction: Direction
    level: Decimal
    wick_ratio: float


@dataclass
class StructureResult:
    swings: list[Swing] = field(default_factory=list)
    breaks: list[BreakEvent] = field(default_factory=list)
    fvgs: list[FVG] = field(default_factory=list)
    order_blocks: list[OrderBlock] = field(default_factory=list)
    sweeps: list[Sweep] = field(default_factory=list)
    displacements: list[tuple[int, Direction, float]] = field(default_factory=list)
    trend: str = "UNDEFINED"
    last_swing_high: Swing | None = None
    last_swing_low: Swing | None = None
    last_break: BreakEvent | None = None
    last_choch: BreakEvent | None = None
    last_bos: BreakEvent | None = None


def find_swings(candles: list[Candle], k: int) -> list[Swing]:
    swings: list[Swing] = []
    n = len(candles)
    for index in range(k, n - k):
        high = candles[index].high
        low = candles[index].low
        if all(high > candles[left].high for left in range(index - k, index)) and all(
            high >= candles[right].high for right in range(index + 1, index + k + 1)
        ):
            swings.append(Swing(index=index, price=high, kind="HIGH", confirmed_index=index + k))
        if all(low < candles[left].low for left in range(index - k, index)) and all(
            low <= candles[right].low for right in range(index + 1, index + k + 1)
        ):
            swings.append(Swing(index=index, price=low, kind="LOW", confirmed_index=index + k))
    swings.sort(key=lambda swing: (swing.confirmed_index, swing.index))
    return swings


def detect_breaks(candles: list[Candle], swings: list[Swing]) -> list[BreakEvent]:
    events: list[BreakEvent] = []
    pointer = 0
    last_high: Swing | None = None
    last_low: Swing | None = None
    broken_high_key: tuple[int, str] | None = None
    broken_low_key: tuple[int, str] | None = None
    trend = "UNDEFINED"

    for index, candle in enumerate(candles):
        while pointer < len(swings) and swings[pointer].confirmed_index <= index:
            swing = swings[pointer]
            if swing.kind == "HIGH":
                last_high = swing
            else:
                last_low = swing
            pointer += 1

        close = candle.close
        if last_high is not None and close > last_high.price and (last_high.index, last_high.kind) != broken_high_key:
            kind = "CHOCH_UP" if trend == "DOWN" else "BOS_UP"
            events.append(BreakEvent(kind=kind, index=index, level=last_high.price, swing=last_high, trend_before=trend))
            trend = "UP"
            broken_high_key = (last_high.index, last_high.kind)
        elif last_low is not None and close < last_low.price and (last_low.index, last_low.kind) != broken_low_key:
            kind = "CHOCH_DOWN" if trend == "UP" else "BOS_DOWN"
            events.append(BreakEvent(kind=kind, index=index, level=last_low.price, swing=last_low, trend_before=trend))
            trend = "DOWN"
            broken_low_key = (last_low.index, last_low.kind)
    return events


def detect_fvgs(candles: list[Candle], atr: tuple[ind.Number, ...], min_atr: Decimal) -> list[FVG]:
    fvgs: list[FVG] = []
    for index in range(2, len(candles)):
        atr_value = atr[index]
        if atr_value is None:
            continue
        threshold = float(min_atr) * atr_value
        first, third = candles[index - 2], candles[index]
        if third.low > first.high:
            width = third.low - first.high
            if float(width) >= threshold:
                fvgs.append(FVG(index=index, direction=Direction.LONG, zone=PriceZone(low=first.high, high=third.low)))
        elif third.high < first.low:
            width = first.low - third.high
            if float(width) >= threshold:
                fvgs.append(FVG(index=index, direction=Direction.SHORT, zone=PriceZone(low=third.high, high=first.low)))
    return fvgs


def detect_order_blocks(candles: list[Candle], atr: tuple[ind.Number, ...], displacement_atr: Decimal) -> tuple[list[OrderBlock], list[tuple[int, Direction, float]]]:
    blocks: list[OrderBlock] = []
    displacements: list[tuple[int, Direction, float]] = []
    for index in range(3, len(candles)):
        atr_value = atr[index]
        if atr_value is None or atr_value == 0:
            continue
        candle = candles[index]
        body = abs(candle.close - candle.open)
        total_range = candle.high - candle.low
        if total_range <= 0:
            continue
        ratio = float(body / Decimal(str(atr_value)))
        if ratio < float(displacement_atr) or float(body / total_range) < 0.6:
            continue
        direction = Direction.LONG if candle.close > candle.open else Direction.SHORT
        displacements.append((index, direction, ratio))
        for back in range(1, 4):
            candidate_index = index - back
            if candidate_index < 0:
                break
            candidate = candles[candidate_index]
            opposite = (direction is Direction.LONG and candidate.close < candidate.open) or (
                direction is Direction.SHORT and candidate.close > candidate.open
            )
            if opposite:
                blocks.append(
                    OrderBlock(
                        index=index,
                        direction=direction,
                        zone=PriceZone(low=candidate.low, high=candidate.high),
                        displacement_ratio=ratio,
                    )
                )
                break
    return blocks, displacements


def detect_sweeps(candles: list[Candle], lookback: int) -> list[Sweep]:
    sweeps: list[Sweep] = []
    for index in range(lookback, len(candles)):
        candle = candles[index]
        window = candles[index - lookback:index]
        prior_high = max(item.high for item in window)
        prior_low = min(item.low for item in window)
        if candle.high > prior_high and candle.close < prior_high:
            wick = candle.high - max(candle.open, candle.close)
            ratio = float(wick / (candle.high - candle.low)) if candle.high > candle.low else 0.0
            if ratio >= 0.3:
                sweeps.append(Sweep(index=index, direction=Direction.SHORT, level=prior_high, wick_ratio=ratio))
        elif candle.low < prior_low and candle.close > prior_low:
            wick = min(candle.open, candle.close) - candle.low
            ratio = float(wick / (candle.high - candle.low)) if candle.high > candle.low else 0.0
            if ratio >= 0.3:
                sweeps.append(Sweep(index=index, direction=Direction.LONG, level=prior_low, wick_ratio=ratio))
    return sweeps


class StructureModule:
    """ماژول structure.v1: همه شواهد ساختاری در یک پاس."""

    module_id = "structure"
    version = MODULE_VERSION

    def compute(self, context: AnalysisContext, factory: EvidenceFactory) -> StructureResult:
        settings = context.settings
        result = StructureResult()
        result.swings = find_swings(context.candles, settings.swing_k)
        result.breaks = detect_breaks(context.candles, result.swings)
        result.fvgs = detect_fvgs(context.candles, context.indicators.atr, settings.fvg_min_atr)
        result.order_blocks, result.displacements = detect_order_blocks(
            context.candles, context.indicators.atr, settings.displacement_atr
        )
        result.sweeps = detect_sweeps(context.candles, settings.sweep_lookback)

        if result.swings:
            highs = [swing for swing in result.swings if swing.kind == "HIGH"]
            lows = [swing for swing in result.swings if swing.kind == "LOW"]
            result.last_swing_high = highs[-1] if highs else None
            result.last_swing_low = lows[-1] if lows else None
        if result.breaks:
            result.last_break = result.breaks[-1]
            result.trend = "UP" if result.last_break.direction_name == "LONG" else "DOWN"
            choches = [event for event in result.breaks if event.kind.startswith("CHOCH")]
            bosses = [event for event in result.breaks if event.kind.startswith("BOS")]
            result.last_choch = choches[-1] if choches else None
            result.last_bos = bosses[-1] if bosses else None

        for event in result.breaks:
            candle = context.candles[event.index]
            atr = context.indicators.atr[event.index] or 1e-9
            distance_pips = float(abs(candle.close - event.level) / context.instrument.pip_size)
            atr_pips = max(float(atr / float(context.instrument.pip_size)), 0.1)
            strength = clamp(
                0.35 + 0.45 * min(1.0, distance_pips / atr_pips) + (0.08 if event.kind.startswith("BOS") else 0.0),
                0.1,
                0.95,
            )
            direction = Direction.LONG if event.kind.endswith("_UP") else Direction.SHORT
            factory.create(
                module_id=f"structure.{event.kind.lower()}",
                module_version=self.version,
                family=EvidenceFamily.STRUCTURE,
                direction=direction,
                strength=strength,
                confidence=clamp(strength * 0.9, 0, 1),
                observed_at=candle.open_time,
                available_at=candle.available_at,
                explanation=(
                    f"{'شکست ساختار صعودی' if direction is Direction.LONG else 'شکست ساختار نزولی'} "
                    f"با بسته‌شدن کندل روی سطح {format(event.level, 'f')} "
                    f"(سوئینگ {format_ts(context.candles[event.swing.index].open_time)})."
                ),
                invalidation={
                    "condition": "close_below" if direction is Direction.LONG else "close_above",
                    "level": format(event.level, "f"),
                },
                expiry=context.expiry(event.index),
                source_refs=(context.bar_ref(event.index), context.bar_ref(event.swing.index)),
                params={"swing_k": settings.swing_k, "kind": event.kind},
            )

        for fvg in result.fvgs:
            candle = context.candles[fvg.index]
            atr = context.indicators.atr[fvg.index] or 1e-9
            width_ratio = float(fvg.zone.width) / float(atr)
            strength = clamp(0.30 + 0.45 * min(1.0, width_ratio), 0.15, 0.85)
            factory.create(
                module_id="structure.fvg",
                module_version=self.version,
                family=EvidenceFamily.STRUCTURE,
                direction=fvg.direction,
                strength=strength,
                confidence=clamp(strength * 0.8, 0, 1),
                observed_at=candle.open_time,
                available_at=candle.available_at,
                explanation=(
                    f"FVG {'صعودی' if fvg.direction is Direction.LONG else 'نزولی'} در محدوده "
                    f"{format(fvg.zone.low, 'f')} تا {format(fvg.zone.high, 'f')}."
                ),
                zone=fvg.zone,
                invalidation={
                    "condition": "close_below" if fvg.direction is Direction.LONG else "close_above",
                    "level": format(fvg.zone.low if fvg.direction is Direction.LONG else fvg.zone.high, "f"),
                },
                expiry=context.expiry(fvg.index),
                source_refs=tuple(context.bar_ref(i) for i in (fvg.index - 2, fvg.index - 1, fvg.index)),
                params={"fvg_min_atr": format(settings.fvg_min_atr, "f")},
            )

        for block in result.order_blocks:
            candle = context.candles[block.index]
            strength = clamp(0.40 + 0.30 * min(1.0, block.displacement_ratio - float(settings.displacement_atr)), 0.2, 0.85)
            factory.create(
                module_id="structure.order_block",
                module_version=self.version,
                family=EvidenceFamily.STRUCTURE,
                direction=block.direction,
                strength=strength,
                confidence=clamp(strength * 0.75, 0, 1),
                observed_at=candle.open_time,
                available_at=candle.available_at,
                explanation=(
                    f"Order Block {'صعودی' if block.direction is Direction.LONG else 'نزولی'} "
                    f"در محدوده {format(block.zone.low, 'f')} تا {format(block.zone.high, 'f')} "
                    f"پیش از displacement {block.displacement_ratio:.2f}×ATR."
                ),
                zone=block.zone,
                invalidation={
                    "condition": "close_below" if block.direction is Direction.LONG else "close_above",
                    "level": format(block.zone.low if block.direction is Direction.LONG else block.zone.high, "f"),
                },
                expiry=context.expiry(block.index),
                source_refs=(context.bar_ref(block.index),),
                params={"displacement_atr": format(settings.displacement_atr, "f")},
            )

        for sweep in result.sweeps:
            candle = context.candles[sweep.index]
            strength = clamp(0.35 + 0.4 * sweep.wick_ratio, 0.2, 0.9)
            factory.create(
                module_id="structure.liquidity_sweep",
                module_version=self.version,
                family=EvidenceFamily.STRUCTURE,
                direction=sweep.direction,
                strength=strength,
                confidence=clamp(strength * 0.85, 0, 1),
                observed_at=candle.open_time,
                available_at=candle.available_at,
                explanation=(
                    f"جاروب نقدینگی روی سطح {format(sweep.level, 'f')} و بازگشت بسته‌شدن "
                    f"({'بالای' if sweep.direction is Direction.SHORT else 'پایین'} سطح)."
                ),
                invalidation={
                    "condition": "close_above" if sweep.direction is Direction.SHORT else "close_below",
                    "level": format(sweep.level, "f"),
                },
                expiry=context.expiry(sweep.index),
                source_refs=(context.bar_ref(sweep.index),),
                params={"sweep_lookback": settings.sweep_lookback},
            )

        for index, direction, ratio in result.displacements:
            candle = context.candles[index]
            strength = clamp(0.35 + 0.35 * min(1.0, ratio - float(settings.displacement_atr)), 0.2, 0.85)
            factory.create(
                module_id="structure.displacement",
                module_version=self.version,
                family=EvidenceFamily.STRUCTURE,
                direction=direction,
                strength=strength,
                confidence=clamp(strength * 0.7, 0, 1),
                observed_at=candle.open_time,
                available_at=candle.available_at,
                explanation=f"Displacement {('صعودی' if direction is Direction.LONG else 'نزولی')} با دامنه {ratio:.2f}×ATR.",
                invalidation=None,
                expiry=context.expiry(index),
                source_refs=(context.bar_ref(index),),
                params={"displacement_atr": format(settings.displacement_atr, "f")},
            )

        return result
