"""تولید داده شبیه‌سازی‌شده قطعی برای دمو/آزمون.

هیچ‌کدام از این داده‌ها نماینده بازار واقعی نیست؛ فقط برای اجرای کامل خط لوله و
آزمون‌های بازتولیدپذیری استفاده می‌شود (seed ثبت‌شده).
"""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fxars.core.numerics import quantize, to_decimal
from fxars.core.timeutil import UTC, format_ts, utcnow
from fxars.domain.enums import EventImportance, Timeframe
from fxars.domain.models import Candle, EconomicEvent, Instrument
from fxars.instruments.calendar import (
    TradingCalendar,
    default_early_closes,
    default_holidays,
    default_metal_holidays,
)

BASE_PRICES: dict[str, Decimal] = {
    "EURUSD": Decimal("1.08500"),
    "GBPUSD": Decimal("1.26500"),
    "AUDUSD": Decimal("0.65500"),
    "USDJPY": Decimal("149.500"),
    "USDCHF": Decimal("0.88500"),
    "XAUUSD": Decimal("2350.00"),
    "DXY": Decimal("104.200"),
}

ANNUAL_VOL: dict[str, float] = {
    "EURUSD": 0.085,
    "GBPUSD": 0.095,
    "AUDUSD": 0.100,
    "USDJPY": 0.090,
    "USDCHF": 0.085,
    "XAUUSD": 0.160,
    "DXY": 0.060,
}


def _bar_sigma(annual_vol: float, timeframe: str) -> float:
    minutes = Timeframe.parse(timeframe).minutes
    bars_per_year = 252 * 24 * 60 / minutes
    return annual_vol / math.sqrt(bars_per_year)


def generate_candles(
    instrument: Instrument,
    start: datetime,
    bars: int,
    *,
    timeframe: str = "H1",
    seed: int = 7,
    calendar: TradingCalendar | None = None,
    base_price: Decimal | None = None,
    annual_vol: float | None = None,
    source_id: str = "demo_feed",
) -> list[Candle]:
    """تولید مسیر قیمت با رژیم‌های روند/رنج و نوسان خوشه‌ای."""
    calendar = calendar or TradingCalendar()
    tf = Timeframe.parse(timeframe)
    rng = random.Random(seed)
    sigma = _bar_sigma(annual_vol if annual_vol is not None else ANNUAL_VOL.get(instrument.instrument_id, 0.09), tf.value)
    price = base_price if base_price is not None else BASE_PRICES.get(instrument.instrument_id, Decimal("1.0"))
    price = to_decimal(price)

    horizon_days = math.ceil(bars * tf.minutes / (60 * 24 * 5 / 7)) + 14
    times = calendar.expected_bar_times(
        start, start + timedelta(days=horizon_days), tf, instrument_id=instrument.instrument_id,
    )[:bars]
    if len(times) < bars:
        raise ValueError("افق زمانی برای تولید تعداد کافی کندل کافی نیست.")

    candles: list[Candle] = []
    drift = 0.0
    regime_left = 0
    vol_multiplier = 1.0
    for index, open_time in enumerate(times):
        if regime_left <= 0:
            regime = rng.choice(["up", "down", "range", "range"])
            if regime == "up":
                drift = sigma * 0.18
            elif regime == "down":
                drift = -sigma * 0.18
            else:
                drift = 0.0
            regime_left = rng.randint(80, 320)
            vol_multiplier = 0.8 + rng.random() * 0.6
        regime_left -= 1

        shock = rng.gauss(0.0, 1.0)
        if rng.random() < 0.004:
            shock *= 3.2  # جهش نادر
        ret = drift + sigma * vol_multiplier * shock
        # تمایل بازگشتی ملایم به قیمت پایه برای جلوگیری از انحراف بلندمدت
        anchor = float(BASE_PRICES.get(instrument.instrument_id, price)) if base_price is None else float(base_price)
        ret += 0.000015 * (anchor - float(price)) / max(float(price), 1e-9)

        open_price = price
        close_price = open_price * Decimal(str(1.0 + ret))
        wick = abs(rng.gauss(0.0, 1.0)) * sigma * 0.55
        high_price = max(open_price, close_price) * Decimal(str(1.0 + wick))
        low_price = min(open_price, close_price) * Decimal(str(1.0 - wick))

        digits = instrument.digits
        open_q = quantize(open_price, digits)
        close_q = quantize(close_price, digits)
        high_q = max(quantize(high_price, digits), open_q, close_q)
        low_q = min(quantize(low_price, digits), open_q, close_q)
        if high_q <= low_q:
            high_q = low_q + instrument.point

        range_pips = float((high_q - low_q) / instrument.pip_size)
        spread_pips = max(0.4, rng.gauss(1.0, 0.35)) * (1.0 + 0.15 * (vol_multiplier - 1.0))
        volume = int(250 + 90 * range_pips + abs(rng.gauss(0.0, 1.0)) * 600)
        available_at = open_time + tf.delta + timedelta(seconds=2)
        candles.append(
            Candle(
                instrument_id=instrument.instrument_id,
                source_id=source_id,
                timeframe=tf.value,
                open_time=open_time,
                open=open_q,
                high=high_q,
                low=low_q,
                close=close_q,
                tick_volume=max(1, volume),
                spread=quantize(Decimal(str(spread_pips)) * instrument.pip_size, instrument.digits + 1),
                is_closed=True,
                quality_status="VALID",
                ingested_at=available_at + timedelta(seconds=1),
                available_at=available_at,
            )
        )
        price = close_q
        _ = index
    return candles


def generate_reference_candles(
    base_candles: list[Candle],
    instrument: Instrument,
    *,
    seed: int = 11,
    correlation: float = -0.85,
    source_id: str = "demo_ref",
    base_price: Decimal | None = None,
) -> list[Candle]:
    """سری مرجع بین‌بازاری (مثلاً DXY) با همبستگی منفی به EURUSD."""
    rng = random.Random(seed)
    price = base_price if base_price is not None else BASE_PRICES.get(instrument.instrument_id, Decimal("100"))
    candles: list[Candle] = []
    for base in base_candles:
        base_return = float((base.close - base.open) / base.open)
        noise = rng.gauss(0.0, 0.00045)
        ret = correlation * base_return + noise
        open_price = price
        close_price = open_price * Decimal(str(1.0 + ret))
        wick = abs(rng.gauss(0.0, 1.0)) * abs(ret) * 0.5 + float(open_price) * 0.00005
        high_price = max(open_price, close_price) * Decimal(str(1.0 + wick))
        low_price = min(open_price, close_price) * Decimal(str(1.0 - wick))
        open_q = quantize(open_price, instrument.digits)
        close_q = quantize(close_price, instrument.digits)
        high_q = max(quantize(high_price, instrument.digits), open_q, close_q)
        low_q = min(quantize(low_price, instrument.digits), open_q, close_q)
        candles.append(
            Candle(
                instrument_id=instrument.instrument_id,
                source_id=source_id,
                timeframe=base.timeframe,
                open_time=base.open_time,
                open=open_q,
                high=high_q,
                low=low_q,
                close=close_q,
                tick_volume=max(1, int(200 + abs(rng.gauss(0, 1)) * 300)),
                spread=quantize(Decimal("0.001"), instrument.digits),
                is_closed=True,
                quality_status="VALID",
                ingested_at=base.available_at + timedelta(seconds=1),
                available_at=base.available_at,
            )
        )
        price = close_q
    return candles


EVENT_DEFINITIONS = {
    "NFP": {"currency": "USD", "country": "US", "importance": EventImportance.HIGH, "unit": "K",
            "forecast": Decimal("180"), "indicator": "Non-Farm Payrolls", "hour": 13, "minute": 30},
    "CPI": {"currency": "USD", "country": "US", "importance": EventImportance.HIGH, "unit": "%",
            "forecast": Decimal("3.0"), "indicator": "CPI YoY", "hour": 13, "minute": 30},
    "FOMC": {"currency": "USD", "country": "US", "importance": EventImportance.HIGH, "unit": "%",
             "forecast": Decimal("4.25"), "indicator": "Fed Funds Rate", "hour": 19, "minute": 0},
    "ECB": {"currency": "EUR", "country": "EU", "importance": EventImportance.HIGH, "unit": "%",
            "forecast": Decimal("3.25"), "indicator": "ECB Deposit Rate", "hour": 12, "minute": 45},
    "BOE": {"currency": "GBP", "country": "GB", "importance": EventImportance.MEDIUM, "unit": "%",
            "forecast": Decimal("4.75"), "indicator": "BoE Bank Rate", "hour": 12, "minute": 0},
    "BOJ": {"currency": "JPY", "country": "JP", "importance": EventImportance.MEDIUM, "unit": "%",
            "forecast": Decimal("0.50"), "indicator": "BoJ Policy Rate", "hour": 3, "minute": 0},
}


def _first_weekday(year: int, month: int, weekday: int) -> datetime:
    day = datetime(year, month, 1, tzinfo=UTC)
    offset = (weekday - day.weekday()) % 7
    return day + timedelta(days=offset)


def _events_for_month(year: int, month: int, rng: random.Random) -> list[EconomicEvent]:
    events: list[EconomicEvent] = []
    schedule: list[tuple[str, datetime]] = []
    nfp = _first_weekday(year, month, 4).replace(hour=13, minute=30)
    schedule.append(("NFP", nfp))
    cpi = datetime(year, month, 12, 13, 30, tzinfo=UTC)
    while cpi.weekday() >= 5:
        cpi += timedelta(days=1)
    schedule.append(("CPI", cpi))
    schedule.append(("FOMC", _first_weekday(year, month, 2).replace(hour=19, minute=0) + timedelta(days=14)))
    schedule.append(("ECB", _first_weekday(year, month, 3).replace(hour=12, minute=45)))
    schedule.append(("BOE", _first_weekday(year, month, 3).replace(hour=12, minute=0)))
    schedule.append(("BOJ", _first_weekday(year, month, 4).replace(hour=3, minute=0) + timedelta(days=21)))

    for kind, event_time in schedule:
        definition = EVENT_DEFINITIONS[kind]
        forecast = definition["forecast"]
        surprise = Decimal(str(rng.gauss(0.0, 0.18))) * abs(forecast) if forecast != 0 else Decimal("0")
        actual = (forecast + surprise).quantize(Decimal("0.01"))
        previous = (forecast + Decimal(str(rng.gauss(0.0, 0.1))) * abs(forecast)).quantize(Decimal("0.01"))
        event_id = f"evt_{kind.lower()}_{event_time.strftime('%Y%m%d')}"
        events.append(
            EconomicEvent(
                event_id=event_id,
                indicator=definition["indicator"],
                currency=definition["currency"],
                country=definition["country"],
                event_time=event_time,
                published_at=event_time + timedelta(seconds=30),
                available_at=event_time + timedelta(minutes=2),
                importance=definition["importance"],
                actual=actual,
                forecast=forecast,
                previous=previous,
                unit=definition["unit"],
                source_id="demo_calendar",
            )
        )
    return events


def generate_economic_events(start: datetime, end: datetime, *, seed: int = 13) -> list[EconomicEvent]:
    rng = random.Random(seed)
    events: list[EconomicEvent] = []
    start = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
    end = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)
    cursor = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor <= end:
        events.extend(_events_for_month(cursor.year, cursor.month, rng))
        cursor = (cursor.replace(day=28) + timedelta(days=5)).replace(day=1)
    return [event for event in sorted(events, key=lambda item: item.event_time) if start <= event.event_time <= end]


def write_events_csv(events: list[EconomicEvent], path: str | Path) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["event_id", "indicator", "currency", "country", "event_time_utc", "published_at_utc", "available_at_utc",
               "importance", "actual", "forecast", "previous", "unit", "source_id"]
    with open(file_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for event in events:
            writer.writerow({
                "event_id": event.event_id,
                "indicator": event.indicator,
                "currency": event.currency,
                "country": event.country,
                "event_time_utc": format_ts(event.event_time),
                "published_at_utc": format_ts(event.published_at) if event.published_at else "",
                "available_at_utc": format_ts(event.available_at),
                "importance": event.importance.value,
                "actual": "" if event.actual is None else format(event.actual, "f"),
                "forecast": "" if event.forecast is None else format(event.forecast, "f"),
                "previous": "" if event.previous is None else format(event.previous, "f"),
                "unit": event.unit,
                "source_id": event.source_id,
            })


def read_events_csv(path: str | Path) -> list[EconomicEvent]:
    from fxars.core.timeutil import parse_ts

    events: list[EconomicEvent] = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            events.append(
                EconomicEvent(
                    event_id=row["event_id"],
                    indicator=row["indicator"],
                    currency=row["currency"],
                    country=row["country"],
                    event_time=parse_ts(row["event_time_utc"]),
                    published_at=parse_ts(row["published_at_utc"]) if row.get("published_at_utc") else None,
                    available_at=parse_ts(row["available_at_utc"]),
                    importance=row["importance"],
                    actual=Decimal(row["actual"]) if row.get("actual") else None,
                    forecast=Decimal(row["forecast"]) if row.get("forecast") else None,
                    previous=Decimal(row["previous"]) if row.get("previous") else None,
                    unit=row.get("unit", ""),
                    source_id=row.get("source_id", "demo_calendar"),
                )
            )
    return events


def demo_start() -> datetime:
    """شروع داده دمو: یکشنبه شب پیش از فوریه ۲۰۲۶ (بازگشایی بازار)."""
    return datetime(2026, 2, 1, 22, 0, tzinfo=UTC)


def demo_end(calendar: TradingCalendar | None = None) -> datetime:
    """پایان داده دمو: جمعه پیش از تاریخ مرجع سند."""
    return datetime(2026, 10, 30, 21, 0, tzinfo=UTC)


def generate_demo_bundle(output_dir: str | Path, *, instrument_ids: tuple[str, ...] = ("EURUSD",),
                         bars: int = 4658, seed: int = 7, calendar: TradingCalendar | None = None) -> dict[str, object]:
    """تولید CSV کندل‌ها، سری مرجع DXY و تقویم اقتصادی؛ خروجی مسیرها."""
    from fxars.data.providers import write_candle_csv
    from fxars.instruments.spec import default_instruments

    calendar = calendar or TradingCalendar(
        default_holidays(),
        early_closes=default_early_closes(),
        metal_holidays=default_metal_holidays(),
    )
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    specs = {instrument.instrument_id: instrument for instrument in default_instruments()}
    outputs: dict[str, object] = {"candles": {}, "events": None, "reference": None}
    start = demo_start()

    primary_candles: list[Candle] = []
    for instrument_id in instrument_ids:
        instrument = specs[instrument_id]
        candles = generate_candles(instrument, start, bars, seed=seed, calendar=calendar)
        path = directory / f"{instrument_id}_H1.csv"
        write_candle_csv(candles, path)
        outputs["candles"][instrument_id] = {"path": str(path), "count": len(candles),
                                             "first": format_ts(candles[0].open_time),
                                             "last": format_ts(candles[-1].open_time)}
        if instrument_id == "EURUSD":
            primary_candles = candles
            reference = generate_reference_candles(primary_candles, specs["DXY"], seed=seed + 4)
            reference_path = directory / "DXY_H1.csv"
            write_candle_csv(reference, reference_path)
            outputs["reference"] = {"path": str(reference_path), "count": len(reference)}

    if primary_candles:
        events = generate_economic_events(primary_candles[0].open_time - timedelta(days=7),
                                          primary_candles[-1].open_time + timedelta(days=7), seed=seed + 2)
        events_path = directory / "economic_events.csv"
        write_events_csv(events, events_path)
        outputs["events"] = {"path": str(events_path), "count": len(events)}
    outputs["generated_at"] = format_ts(utcnow())
    return outputs
