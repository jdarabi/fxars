"""اجرای Forward Test event-time روی یک دیتابیس.

نمونه:
    python scripts/forward_test.py --db data/forward_test.db --instrument EURUSD --timeframe H1

توجه: تحلیل‌ها در همان دیتابیس ثبت می‌شوند؛ برای داده واقعی از کپی دیتابیس
عملیاتی استفاده کنید و هرگز روی دیتابیس production به‌صورت مستقیم اجرا نکنید.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.config.settings import Settings
from fxars.core.timeutil import parse_ts
from fxars.domain.enums import Phase
from fxars.live.forward_test import ForwardTestHarness
from fxars.platform import Platform


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FX-ARS forward test harness")
    parser.add_argument("--db", required=True, help="مسیر دیتابیس forward-test")
    parser.add_argument("--instrument", default="EURUSD")
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--warmup", type=int, default=300)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=None, help="حداکثر گام‌های آزمون")
    parser.add_argument("--as-of", default=None, help="ISO timestamp (پیش‌فرض: اکنون)")
    parser.add_argument("--json", action="store_true", help="خروجی JSON کامل")
    args = parser.parse_args(argv)

    as_of = parse_ts(args.as_of) if args.as_of else None
    settings = Settings.from_dict({
        "phase": Phase.READ_ONLY.value,
        "db_path": args.db,
        "environment": "dev",
    })
    platform = Platform(settings, sync_phase=False)
    try:
        platform.bootstrap(create_users=False)
        report = ForwardTestHarness(
            platform, args.instrument, args.timeframe,
            warmup=args.warmup, step_size=args.step,
        ).run(as_of=as_of, max_steps=args.max_steps)
    finally:
        platform.close()

    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"نماد: {payload['instrument_id']}/{payload['timeframe']}")
        print(f"بازه: {payload['start']} → {payload['end']} | کندل آزمون‌شده: {payload['candles_tested']}")
        print(f"LONG={payload['long']} SHORT={payload['short']} NO_TRADE={payload['no_trade']}")
        print(f"سناریوها: {payload['scenarios']}")
        print(f"خطاها: {len(payload['errors'])} | نقض look-ahead: {len(payload['lookahead_violations'])}")
        print(f"حکم: {payload['verdict']}")
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
