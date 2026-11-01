"""منابع داده: قرارداد Provider و پیاده‌سازی CSV (نقطه اتصال فیدهای واقعی)."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from fxars.core.hashing import sha256_bytes
from fxars.core.numerics import to_decimal
from fxars.core.timeutil import format_ts, parse_ts, utcnow
from fxars.domain.enums import QualityStatus, Timeframe
from fxars.domain.models import Candle, Instrument


class MarketDataProvider(Protocol):
    source_id: str

    def fetch(self, instrument: Instrument, timeframe: str) -> list[Candle]: ...


@dataclass
class CsvLoadResult:
    candles: list[Candle]
    rows: int
    errors: list[dict[str, Any]] = field(default_factory=list)
    path: str = ""
    content_hash: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.candles)


TRUE_VALUES = {"1", "true", "yes", "y", "t"}


def _parse_bool(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in TRUE_VALUES


def read_candle_csv(
    path: str | Path,
    *,
    instrument_id: str,
    source_id: str,
    timeframe: str,
    available_delay_seconds: int = 5,
    now: datetime | None = None,
    strict: bool = False,
) -> CsvLoadResult:
    """خواندن CSV کندل با هدرهای قراردادی (bar_open_time_utc/open_time).

    هر ردیف نامعتبر در errors ثبت و کنار گذاشته می‌شود؛ در حالت strict خطا raise می‌شود.
    """
    file_path = Path(path)
    tf = Timeframe.parse(timeframe)
    raw = file_path.read_bytes()
    result = CsvLoadResult(candles=[], rows=0, path=str(file_path), content_hash=sha256_bytes(raw))
    ingested_at = now or utcnow()

    with open(file_path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("فایل CSV هدر ندارد.")
        normalized = {name.strip().lower(): name for name in reader.fieldnames}
        for index, row in enumerate(reader, start=2):
            result.rows += 1
            try:
                data = {key.lower(): value for key, value in row.items() if key}
                time_value = data.get("bar_open_time_utc") or data.get("open_time") or data.get("time")
                if not time_value:
                    raise ValueError("ستون زمان موجود نیست")
                open_time = parse_ts(time_value)
                candle = Candle(
                    instrument_id=instrument_id,
                    source_id=source_id,
                    timeframe=tf.value,
                    open_time=open_time,
                    open=to_decimal(data["open"], field="open"),
                    high=to_decimal(data["high"], field="high"),
                    low=to_decimal(data["low"], field="low"),
                    close=to_decimal(data["close"], field="close"),
                    tick_volume=int(data["tick_volume"]) if data.get("tick_volume") not in (None, "") else None,
                    spread=to_decimal(data["spread"]) if data.get("spread") not in (None, "") else None,
                    is_closed=_parse_bool(data.get("is_closed"), default=True),
                    quality_status=QualityStatus(data.get("quality_status") or "VALID"),
                    source_revision=data.get("source_revision") or None,
                    ingested_at=ingested_at,
                    available_at=parse_ts(data["available_at"]) if data.get("available_at") else open_time + tf.delta + timedelta(seconds=available_delay_seconds),
                )
                result.candles.append(candle)
            except Exception as exc:  # هر ردیف خراب کل فایل را متوقف نمی‌کند
                result.errors.append({"row": index, "error": str(exc)})
                if strict:
                    raise ValueError(f"ردیف {index} نامعتبر است: {exc}") from exc

    result.candles.sort(key=lambda candle: candle.open_time)
    return result


def write_candle_csv(candles: list[Candle], path: str | Path, *, include_source: bool = False) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["bar_open_time_utc", "open", "high", "low", "close", "tick_volume", "spread", "is_closed", "available_at"]
    if include_source:
        columns.extend(["instrument_id", "source_id", "timeframe"])
    with open(file_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for candle in candles:
            row = {
                "bar_open_time_utc": format_ts(candle.open_time),
                "open": format(candle.open, "f"),
                "high": format(candle.high, "f"),
                "low": format(candle.low, "f"),
                "close": format(candle.close, "f"),
                "tick_volume": "" if candle.tick_volume is None else candle.tick_volume,
                "spread": "" if candle.spread is None else format(candle.spread, "f"),
                "is_closed": "true" if candle.is_closed else "false",
                "available_at": format_ts(candle.available_at),
            }
            if include_source:
                row.update({
                    "instrument_id": candle.instrument_id,
                    "source_id": candle.source_id,
                    "timeframe": candle.timeframe,
                })
            writer.writerow(row)
