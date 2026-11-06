"""History downloader: fetch candles from MT5 for any symbol/timeframe and save as CSV."""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fxars.core.timeutil import format_ts
from fxars.domain.models import Candle

logger = logging.getLogger("fxars.live.history")

TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1",
}


def download_from_mt5(
    *,
    symbol: str,
    timeframe: str,
    bars: int = 5000,
    start: datetime | None = None,
    end: datetime | None = None,
    mt5=None,
) -> list[Candle]:
    """Fetch candles from MT5. If mt5 is None, initialize."""
    if mt5 is None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise RuntimeError("MetaTrader5 package not installed") from exc
        if not mt5.initialize():
            code, msg = mt5.last_error()
            raise RuntimeError(f"MT5 initialize failed: ({code}) {msg}")

    tf_key = TIMEFRAME_MAP.get(timeframe.upper())
    if tf_key is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    tf_const = getattr(mt5, tf_key)

    if start is not None and end is not None:
        # Range fetch
        rates = mt5.copy_rates_range(symbol, tf_const, start, end)
    elif start is not None:
        rates = mt5.copy_rates_from(symbol, tf_const, start, bars)
    elif end is not None:
        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, bars)
    else:
        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, bars)

    if rates is None or len(rates) == 0:
        code, msg = mt5.last_error()
        raise RuntimeError(f"copy_rates failed for {symbol}/{timeframe}: ({code}) {msg}")

    # Get symbol point for spread
    si = mt5.symbol_info(symbol)
    point = Decimal(str(si.point)) if si else Decimal("0.00001")

    candles: list[Candle] = []
    for r in rates:
        open_time = datetime.fromtimestamp(int(r["time"]), tz=UTC)
        candles.append(Candle(
            instrument_id=symbol,
            source_id="mt5",
            timeframe=timeframe.upper(),
            open_time=open_time,
            open=Decimal(str(r["open"])),
            high=Decimal(str(r["high"])),
            low=Decimal(str(r["low"])),
            close=Decimal(str(r["close"])),
            tick_volume=int(r["tick_volume"]) if "tick_volume" in r.dtype.names else None,
            spread=Decimal(str(r["spread"])) * point if "spread" in r.dtype.names and r["spread"] > 0 else None,
            is_closed=True,
            available_at=open_time + _tf_delta(timeframe),
            ingested_at=datetime.now(tz=UTC),
            quality_status="VALID",
        ))
    candles.sort(key=lambda c: c.open_time)
    return candles


def _tf_delta(timeframe: str):
    from fxars.core.timeutil import timeframe_delta
    return timeframe_delta(timeframe.upper())


def save_candles_csv(candles: list[Candle], path: str | Path) -> str:
    """Save candles as CSV compatible with fxars ingest (bar_open_time_utc)."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["bar_open_time_utc", "open", "high", "low", "close", "tick_volume", "spread", "is_closed", "available_at"]
    with open(file_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for c in candles:
            writer.writerow({
                "bar_open_time_utc": format_ts(c.open_time),
                "open": format(c.open, "f"),
                "high": format(c.high, "f"),
                "low": format(c.low, "f"),
                "close": format(c.close, "f"),
                "tick_volume": "" if c.tick_volume is None else c.tick_volume,
                "spread": "" if c.spread is None else format(c.spread, "f"),
                "is_closed": "true",
                "available_at": format_ts(c.available_at),
            })
    return str(file_path)


def download_history(
    *,
    symbols: list[str],
    timeframes: list[str],
    bars: int = 5000,
    start: datetime | None = None,
    end: datetime | None = None,
    output_dir: str | Path = "data/history",
    platform=None,
) -> dict[str, Any]:
    """Download candles for multiple symbols × timeframes. Optionally ingest to platform."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {"files": [], "total": 0, "errors": []}

    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            code, msg = mt5.last_error()
            raise RuntimeError(f"MT5 initialize failed: ({code}) {msg}")
    except ImportError as exc:
        raise RuntimeError("MetaTrader5 package not installed (pip install MetaTrader5)") from exc

    try:
        for symbol in symbols:
            si = mt5.symbol_info(symbol)
            if si is None:
                result["errors"].append(f"{symbol}: symbol not found in MT5")
                print(f"  [SKIP] {symbol}: not in MT5", file=sys.stderr)
                continue
            for tf in timeframes:
                try:
                    print(f"  [{symbol}/{tf}] downloading...", file=sys.stderr)
                    candles = download_from_mt5(
                        symbol=symbol, timeframe=tf, bars=bars,
                        start=start, end=end, mt5=mt5,
                    )
                    if not candles:
                        result["errors"].append(f"{symbol}/{tf}: no candles")
                        continue

                    csv_path = out / f"{symbol}_{tf.upper()}.csv"
                    save_candles_csv(candles, csv_path)
                    result["files"].append(str(csv_path))
                    result["total"] += len(candles)
                    print(f"    saved {len(candles)} candles → {csv_path}", file=sys.stderr)

                    # Optional: ingest to platform
                    if platform is not None:
                        try:
                            ingest = platform.ingestion.ingest(
                                candles, instrument_id=symbol, source_id="mt5",
                                now=datetime.now(tz=UTC),
                            )
                            print(f"    ingested {ingest.accepted}, quarantined {ingest.quarantined}", file=sys.stderr)
                        except Exception as exc:
                            result["errors"].append(f"{symbol}/{tf} ingest: {exc}")
                            print(f"    ingest failed: {exc}", file=sys.stderr)

                except Exception as exc:
                    result["errors"].append(f"{symbol}/{tf}: {exc}")
                    print(f"    ERROR: {exc}", file=sys.stderr)
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fxars download")
    parser.add_argument("--instruments", nargs="+", required=True,
                        help="e.g. EURUSD GBPUSD XAUUSD")
    parser.add_argument("--timeframes", nargs="+", required=True,
                        help="e.g. M15 H1 H4 D1")
    parser.add_argument("--bars", type=int, default=5000,
                        help="number of bars per (symbol, tf)")
    parser.add_argument("--start", default=None,
                        help="ISO-8601 UTC start (optional)")
    parser.add_argument("--end", default=None,
                        help="ISO-8601 UTC end (optional)")
    parser.add_argument("--output-dir", default="data/history")
    parser.add_argument("--ingest", action="store_true",
                        help="also ingest to platform DB")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

    start = None
    end = None
    if args.start:
        from fxars.core.timeutil import parse_ts
        start = parse_ts(args.start)
    if args.end:
        from fxars.core.timeutil import parse_ts
        end = parse_ts(args.end)

    platform = None
    if args.ingest:
        from fxars.config.settings import Settings
        from fxars.platform import Platform
        platform = Platform(Settings.load())
        print("Platform loaded (ingest mode)", file=sys.stderr)

    try:
        result = download_history(
            symbols=args.instruments,
            timeframes=args.timeframes,
            bars=args.bars,
            start=start, end=end,
            output_dir=args.output_dir,
            platform=platform,
        )
        print()
        print(f"Total candles downloaded: {result['total']}")
        print(f"Files: {len(result['files'])}")
        for f in result["files"]:
            print(f"  {f}")
        if result["errors"]:
            print(f"Errors ({len(result['errors'])}):")
            for e in result["errors"][:10]:
                print(f"  {e}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if platform is not None:
            platform.close()


if __name__ == "__main__":
    sys.exit(main())
