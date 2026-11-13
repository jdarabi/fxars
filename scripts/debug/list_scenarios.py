"""فهرست سناریوها روی یک پایگاه دادهٔ صریح (نه تولیدی).

استفاده: python scripts/debug/list_scenarios.py --db <path>
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from fxars.config.settings import PROJECT_ROOT, Settings
from fxars.platform import Platform

PRODUCTION_DB = (PROJECT_ROOT / "data" / "fxars.db").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="List scenarios from an explicit database.")
    parser.add_argument("--db", required=True, help="مسیر پایگاه داده؛ پایگاه تولیدی پذیرفته نمی‌شود.")
    args = parser.parse_args()
    db_path = Path(args.db).resolve()
    if db_path == PRODUCTION_DB:
        parser.error("پایگاه تولیدی مجاز نیست؛ ابتدا یک کپی بگیرید و مسیر کپی را بدهید.")
    platform = Platform(Settings.from_dict({"db_path": str(db_path)}))
    try:
        scenarios = platform.scenarios.list(limit=100)
        print(f"Total scenarios: {len(scenarios)}")
        if scenarios:
            print(f"Status: {dict(Counter(s.status.value for s in scenarios))}")
            print(f"Inst:   {dict(Counter(s.instrument_id for s in scenarios))}")
            print(f"TF:     {dict(Counter(s.timeframe for s in scenarios))}")
            print()
            for scenario in scenarios[:20]:
                sid = scenario.scenario_id[:24]
                print(
                    f"  {sid:24s} {scenario.instrument_id:8s} {scenario.timeframe:4s} "
                    f"{scenario.status.value:10s} {scenario.direction.value}"
                )
        else:
            print("no scenarios in DB")
    finally:
        platform.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
