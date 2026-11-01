"""شناسه Snapshot داده برای بازتولید (AC-02)."""

from __future__ import annotations

from datetime import datetime

from fxars.core.hashing import sha256_obj
from fxars.core.ids import stable_id
from fxars.domain.models import Candle


def candles_digest(candles: list[Candle] | tuple[Candle, ...]) -> str:
    """هش محتوای کندل‌ها (بدون ingested_at) به ترتیب زمان."""
    return sha256_obj([candle.hash_payload() for candle in candles])


def snapshot_id(candles: list[Candle] | tuple[Candle, ...], instrument_id: str, timeframe: str) -> str:
    return stable_id("snap", instrument_id, timeframe, candles_digest(candles))


def available_at(candles: list[Candle], as_of: datetime) -> list[Candle]:
    """فقط کندل‌هایی که در زمان as_of واقعاً در دسترس بوده‌اند."""
    return [candle for candle in candles if candle.available_at <= as_of]


def latest_closed(candles: list[Candle], as_of: datetime) -> Candle | None:
    usable = [c for c in candles if c.is_closed and c.available_at <= as_of]
    return usable[-1] if usable else None
