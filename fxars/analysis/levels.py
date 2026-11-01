"""سطوح کلیدی: سقف/کف روز و هفته قبل، سطوح سشن و اعداد گرد.

هدف: شواهد زمینه‌ای (Context) با جهت حمایت/مقاومت و شدت محدود؛ نه سیگنال مستقل.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fxars.analysis.context import AnalysisContext
from fxars.analysis.evidence import EvidenceFactory
from fxars.core.numerics import clamp
from fxars.core.timeutil import format_ts
from fxars.domain.enums import Direction, EvidenceFamily, SessionName, Timeframe
from fxars.domain.models import Candle, Evidence, PriceZone

MODULE_VERSION = "1.0.0"


@dataclass(frozen=True)
class Level:
    price: Decimal
    kind: str
    touches: int = 1
    strength_hint: float = 0.0


def _aggregate(candles: list[Candle]) -> dict[date, tuple[Decimal, Decimal, Decimal]]:
    result: dict[date, tuple[Decimal, Decimal, Decimal]] = {}
    for candle in candles:
        day = candle.open_time.date()
        high, low, close = result.get(day, (candle.high, candle.low, candle.close))
        result[day] = (max(high, candle.high), min(low, candle.low), candle.close)
    return result


class LevelsModule:
    module_id = "levels"
    version = MODULE_VERSION

    def compute(self, context: AnalysisContext, factory: EvidenceFactory) -> list[Evidence]:
        settings = context.settings
        instrument = context.instrument
        proximity = Decimal(str(settings.level_proximity_pips)) * instrument.pip_size
        merge_distance = Decimal(str(settings.level_merge_pips)) * instrument.pip_size
        round_step = instrument.pip_size * Decimal(50)

        daily = _aggregate(context.candles)
        dates = sorted(daily)
        weekly = _weekly_aggregates(context.candles)

        current_date: date | None = None
        sessions_today: dict[SessionName, tuple[Decimal, Decimal]] = {}
        seen: dict[tuple[str, Decimal], int] = {}
        evidences: list[Evidence] = []
        warmup = max(settings.swing_k * 2, 30)

        for index in range(warmup, len(context.candles)):
            candle = context.candles[index]
            close = candle.close
            bar_date = candle.open_time.date()
            if bar_date != current_date:
                current_date = bar_date
                sessions_today = {}
            prior_dates = [day for day in dates if day < bar_date]
            candidates: list[Level] = []
            if prior_dates:
                prior_day = daily[prior_dates[-1]]
                candidates.append(Level(prior_day[0], "PDH", 2, 0.05))
                candidates.append(Level(prior_day[1], "PDL", 2, 0.05))
            prior_weeks = [week for week in weekly if week < current_date.isocalendar()[:2]]
            if prior_weeks:
                week_key = prior_weeks[-1]
                week_high, week_low = weekly[week_key]
                candidates.append(Level(week_high, "PWH", 3, 0.1))
                candidates.append(Level(week_low, "PWL", 3, 0.1))

            base = (Decimal(int(close / round_step)) * round_step) if round_step > 0 else close
            candidates.append(Level(base, "ROUND", 1, 0.0))
            candidates.append(Level(base + round_step, "ROUND", 1, 0.0))
            if base > 0:
                candidates.append(Level(base - round_step, "ROUND", 1, 0.0))

            window = context.candles[max(0, index - 50):index]
            if window:
                candidates.append(Level(max(item.high for item in window), "SWING_HIGH", 1, 0.0))
                candidates.append(Level(min(item.low for item in window), "SWING_LOW", 1, 0.0))

            # سطوح سشن‌های تکمیل‌شده امروز
            sessions = context.calendar.sessions_at(candle.open_time)
            for session in sessions:
                high, low = sessions_today.get(session, (candle.high, candle.low))
                sessions_today[session] = (max(high, candle.high), min(low, candle.low))
            active = set(sessions)
            for session, (high, low) in sessions_today.items():
                if session not in active:
                    candidates.append(Level(high, f"SESSION_{session.value}_HIGH", 1, 0.0))
                    candidates.append(Level(low, f"SESSION_{session.value}_LOW", 1, 0.0))

            nearest = min((abs(level.price - close) for level in candidates), default=Decimal("999999"))
            if nearest > proximity:
                continue
            merged = _merge_levels(candidates, merge_distance)
            emitted = 0
            for level in sorted(merged, key=lambda item: abs(item.price - close)):
                if abs(level.price - close) > proximity:
                    continue
                key = (level.kind.split("_")[0], level.price)
                if index - seen.get(key, -10_000) < 8:
                    continue
                seen[key] = index
                direction = Direction.LONG if level.price <= close else Direction.SHORT
                closeness = 1.0 - float(abs(level.price - close) / proximity) if proximity > 0 else 0.0
                strength = clamp(0.20 + 0.06 * min(level.touches, 3) + 0.20 * closeness + level.strength_hint, 0.15, 0.70)
                role = "حمایت" if direction is Direction.LONG else "مقاومت"
                evidences.append(
                    factory.create(
                        module_id="levels.key_level",
                        module_version=self.version,
                        family=EvidenceFamily.LEVELS,
                        direction=direction,
                        strength=strength,
                        confidence=clamp(strength * 0.8, 0, 1),
                        observed_at=candle.open_time,
                        available_at=candle.available_at,
                        explanation=(
                            f"قیمت نزدیک سطح {role} {level.kind} در {format(level.price, 'f')} "
                            f"(فاصله {abs(level.price - close) / instrument.pip_size:.1f} پیپ)."
                        ),
                        zone=PriceZone(low=level.price - instrument.pip_size, high=level.price + instrument.pip_size),
                        invalidation={
                            "condition": "close_below" if direction is Direction.LONG else "close_above",
                            "level": format(level.price, "f"),
                        },
                        expiry=context.expiry(index, bars=4),
                        source_refs=(context.bar_ref(index),),
                        params={
                            "proximity_pips": format(settings.level_proximity_pips, "f"),
                            "merge_pips": format(settings.level_merge_pips, "f"),
                            "kind": level.kind,
                        },
                    )
                )
                emitted += 1
                if emitted >= 2:
                    break
        return evidences


def _merge_levels(levels: list[Level], distance: Decimal) -> list[Level]:
    ordered = sorted(levels, key=lambda item: item.price)
    merged: list[Level] = []
    touches = 1
    for level in ordered:
        if merged and abs(level.price - merged[-1].price) <= distance:
            previous = merged[-1]
            touches += level.touches
            merged[-1] = Level(
                price=(previous.price * previous.touches + level.price * level.touches) / (previous.touches + level.touches),
                kind=previous.kind,
                touches=touches,
                strength_hint=max(previous.strength_hint, level.strength_hint),
            )
        else:
            merged.append(level)
            touches = 1
    return merged


def _weekly_aggregates(candles: list[Candle]) -> dict[tuple[int, int], tuple[Decimal, Decimal]]:
    """سقف/کف هر هفته ISO بر اساس کندل‌های موجود."""
    buckets: dict[tuple[int, int], tuple[Decimal, Decimal]] = {}
    for candle in candles:
        year, week, _ = candle.open_time.isocalendar()
        key = (year, week)
        high, low = buckets.get(key, (candle.high, candle.low))
        buckets[key] = (max(high, candle.high), min(low, candle.low))
    return buckets
