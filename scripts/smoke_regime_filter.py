"""Smoke test for regime filter (used in CI)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.domain.enums import BacktestSegment
from fxars.platform import Platform


def main() -> int:
    platform = Platform()
    platform.bootstrap(create_users=False)
    base = platform.run_backtest("EURUSD", "H1", segment=BacktestSegment.ALL)
    filtered = platform.run_backtest(
        "EURUSD", "H1",
        overrides={"allowed_regimes": ["TRENDING_UP", "TRENDING_DOWN"]},
        segment=BacktestSegment.ALL,
    )
    print("baseline: trades={} net={:.2f}".format(
        base.run.metrics["trade_count"], base.run.metrics["net_profit"]))
    print("filtered: trades={} net={:.2f}".format(
        filtered.run.metrics["trade_count"], filtered.run.metrics["net_profit"]))
    assert filtered.run.metrics["trade_count"] <= base.run.metrics["trade_count"]
    platform.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
