# C:\FX\seed_all_timeframes.py
"""تولید داده دمو برای همه نمادها × همه تایم‌فریم‌ها (M5 به بالا).

- بازهٔ زمانی مشترک: Feb 2026 → Oct 2026 (۹ ماه)
- تعداد کندل بسته به تایم‌فریم
- DXY فقط یک بار به‌عنوان reference
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(r'C:\FX')
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.data.providers import write_candle_csv
from fxars.data.synthetic import demo_start, generate_candles, generate_reference_candles
from fxars.instruments.calendar import TradingCalendar, default_holidays
from fxars.platform import Platform

# نمادهای قابل معامله (بدون DXY)
TRADEABLE = ("EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCHF", "XAUUSD")

# تایم‌فریم‌ها از M5 به بالا
TIMEFRAMES = ("M5", "M15", "M30", "H1", "H4", "D1", "W1")

# تعداد کندل به تفکیک تایم‌فریم (۹ ماه)
BARS_BY_TF = {
    "M5":  80_000,   # ۲۴ ساعت × ۵ روز × ۴ هفته × ۹ ماه ≈ ۸۰k
    "M15": 27_000,
    "M30": 13_500,
    "H1":  6_500,
    "H4":  1_700,
    "D1":  280,
    "W1":  45,
}

SEED_BASE = 7


def main() -> int:
    t0 = time.time()
    platform = Platform()
    platform.bootstrap(create_users=False)
    try:
        calendar = TradingCalendar(default_holidays())
        start = demo_start()
        data_dir = Path(platform.settings.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)

        print(f"Platform ready. db={platform.settings.db_path}")
        print(f"Data dir: {data_dir}")
        print(f"Start: {start.isoformat()}")
        print()

        primary_candles_by_tf: dict[str, list] = {}

        for tf in TIMEFRAMES:
            bars = BARS_BY_TF[tf]
            print(f"=== Timeframe {tf} ({bars:,} candles × {len(TRADEABLE)} symbols + DXY) ===")
            for symbol in TRADEABLE:
                instrument = platform.instruments.get(symbol)
                seed = SEED_BASE + hash((symbol, tf)) % 1000
                try:
                    candles = generate_candles(
                        instrument, start, bars,
                        timeframe=tf, seed=seed, calendar=calendar,
                    )
                except ValueError as exc:
                    print(f"  [SKIP] {symbol}/{tf}: {exc}")
                    continue
                csv_path = data_dir / f"{symbol}_{tf}.csv"
                write_candle_csv(candles, csv_path)
                result = platform.ingest_csv(
                    csv_path, instrument_id=symbol, timeframe=tf, source_id="demo_feed",
                )
                print(
                    f"  {symbol}/{tf}: generated={len(candles):,} "
                    f"accepted={result.accepted:,} quarantined={result.quarantined} "
                    f"quality={result.quality.verdict if result.quality else '—'}"
                )
                if symbol == "EURUSD":
                    primary_candles_by_tf[tf] = candles

            # DXY reference برای همان timeframe (بر اساس EURUSD)
            if tf in primary_candles_by_tf:
                dxy = platform.instruments.get("DXY")
                primary = primary_candles_by_tf[tf]
                reference = generate_reference_candles(
                    primary, dxy, seed=SEED_BASE + 100 + hash(tf) % 1000,
                )
                ref_path = data_dir / f"DXY_{tf}.csv"
                write_candle_csv(reference, ref_path)
                ref_result = platform.ingest_csv(
                    ref_path, instrument_id="DXY", timeframe=tf, source_id="demo_ref",
                )
                print(
                    f"  DXY/{tf}: generated={len(reference):,} "
                    f"accepted={ref_result.accepted:,} "
                    f"quality={ref_result.quality.verdict if ref_result.quality else '—'}"
                )
            print()

        # خلاصه
        print("=== Summary ===")
        header = "symbol".ljust(8) + "".join(tf.rjust(8) for tf in TIMEFRAMES)
        print(header)
        print("-" * len(header))
        for symbol in TRADEABLE + ("DXY",):
            row = symbol.ljust(8)
            for tf in TIMEFRAMES:
                try:
                    n = platform.candles.count(symbol, tf)
                    row += f"{n:>8,}"
                except Exception:
                    row += "       —"
            print(row)
        print()
        print(f"Elapsed: {time.time() - t0:.1f}s")
        print(f"DB size: {Path(platform.settings.db_path).stat().st_size / 1024 / 1024:.1f} MB")

        # چند نمونه برای تأیید
        print()
        print("=== Sample data ===")
        for symbol, tf in (("EURUSD", "H1"), ("AUDUSD", "M15"), ("XAUUSD", "H4")):
            candles = platform.candles.range(
                symbol, tf, source_id="demo_feed", closed_only=True,
            )
            if candles:
                first = candles[0]
                last = candles[-1]
                print(
                    f"  {symbol}/{tf}: {len(candles):,} candles, "
                    f"{first.open_time.isoformat()} → {last.open_time.isoformat()}, "
                    f"last_close={format(last.close, 'f')}"
                )

        return 0
    finally:
        platform.close()


if __name__ == "__main__":
    raise SystemExit(main())
