"""عیب‌یابی تحلیل چند نماد روی یک پایگاه دادهٔ صریح (نه تولیدی).

استفاده: python scripts/debug/analyze_symbols.py --db <path>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from fxars.config.settings import PROJECT_ROOT, Settings
from fxars.platform import Platform

PRODUCTION_DB = (PROJECT_ROOT / "data" / "fxars.db").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run analysis for a few symbols on an explicit database.")
    parser.add_argument("--db", required=True, help="مسیر پایگاه داده؛ پایگاه تولیدی پذیرفته نمی‌شود.")
    args = parser.parse_args()
    db_path = Path(args.db).resolve()
    if db_path == PRODUCTION_DB:
        parser.error("پایگاه تولیدی مجاز نیست؛ ابتدا یک کپی بگیرید و مسیر کپی را بدهید.")
    platform = Platform(Settings.from_dict({"db_path": str(db_path)}))
    platform.bootstrap(create_users=False)
    try:
        for symbol in ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]:
            for timeframe in ["M15", "H1"]:
                try:
                    result = platform.run_analysis(symbol, timeframe)
                    sid = result.scenario.scenario_id[:12] if result.scenario else "—"
                    print(
                        f"{symbol}/{timeframe}: {result.decision.action.value:8s} "
                        f"scenario={sid:12s} reason={result.scenario_reason}"
                    )
                except Exception as exc:
                    print(f"{symbol}/{timeframe}: ERROR {type(exc).__name__}: {exc}")
    finally:
        platform.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
