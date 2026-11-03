"""Regime filter benchmark suite (P3-5).

Compares baseline (all regimes) vs filtered (TRENDING_UP+DOWN) on the demo
data, saves JSON/Markdown reports, and exits non-zero if the filtered run
is worse than baseline (regression guard).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fxars.domain.enums import BacktestSegment
from fxars.platform import Platform


def _summary(result) -> dict:
    metrics = result.run.metrics
    return {
        "run_id": result.run.run_id,
        "trade_count": metrics.get("trade_count"),
        "net_profit": metrics.get("net_profit"),
        "return_pct": metrics.get("return_pct"),
        "profit_factor": metrics.get("profit_factor"),
        "win_rate": metrics.get("win_rate"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "sharpe": metrics.get("sharpe"),
        "sortino": metrics.get("sortino"),
        "calmar": metrics.get("calmar"),
        "expectancy": metrics.get("expectancy"),
        "dsr": (metrics.get("deflated_sharpe") or {}).get("dsr"),
        "skipped_regime": result.output.stats.get("skipped_regime", 0),
    }


def _delta(base: dict, filtered: dict) -> dict:
    def rel(key):
        b = base.get(key)
        f = filtered.get(key)
        if b is None or f is None or b == 0:
            return None
        try:
            return round((float(f) - float(b)) / abs(float(b)) * 100, 2)
        except (TypeError, ValueError):
            return None

    return {
        "trade_count_pct": rel("trade_count"),
        "net_profit_pct": rel("net_profit"),
        "sharpe_pct": rel("sharpe"),
        "calmar_pct": rel("calmar"),
        "dsr_pct": rel("dsr"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regime filter benchmark")
    parser.add_argument("--instrument", default="EURUSD")
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--segment", default="ALL", choices=["ALL", "TRAIN", "VALIDATION", "LOCKED_TEST"])
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--no-fail-on-regression", action="store_true")
    args = parser.parse_args(argv)

    platform = Platform()
    platform.bootstrap(create_users=False)
    try:
        print(f"Baseline: {args.instrument}/{args.timeframe} ({args.segment})")
        base = platform.run_backtest(
            args.instrument, args.timeframe,
            segment=BacktestSegment(args.segment),
        )
        base_summary = _summary(base)
        print(f"  trades={base_summary['trade_count']} net={base_summary['net_profit']:.2f} "
              f"sharpe={base_summary['sharpe']} dsr={base_summary['dsr']}")

        print(f"Filtered: TRENDING_UP+DOWN")
        filtered = platform.run_backtest(
            args.instrument, args.timeframe,
            overrides={"allowed_regimes": ["TRENDING_UP", "TRENDING_DOWN"]},
            segment=BacktestSegment(args.segment),
        )
        filtered_summary = _summary(filtered)
        print(f"  trades={filtered_summary['trade_count']} net={filtered_summary['net_profit']:.2f} "
              f"sharpe={filtered_summary['sharpe']} dsr={filtered_summary['dsr']} "
              f"skipped_regime={filtered_summary['skipped_regime']}")

        delta = _delta(base_summary, filtered_summary)
        print(f"Delta: net {delta['net_profit_pct']}%, sharpe {delta['sharpe_pct']}%, "
              f"dsr {delta['dsr_pct']}%")

        # Output
        out_dir = Path(args.out_dir) if args.out_dir else (
            ROOT / "reports" / f"benchmark-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "instrument": args.instrument,
            "timeframe": args.timeframe,
            "segment": args.segment,
            "baseline": base_summary,
            "filtered": filtered_summary,
            "delta": delta,
            "timestamp": datetime.now().isoformat(),
        }
        json_path = out_dir / "benchmark.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        md_lines = [
            f"# Regime Filter Benchmark — {args.instrument}/{args.timeframe}",
            "",
            f"- Segment: {args.segment}",
            f"- Timestamp: {payload['timestamp']}",
            "",
            "## Baseline (all regimes)",
            f"- Trades: {base_summary['trade_count']}",
            f"- Net profit: {base_summary['net_profit']:.2f}",
            f"- Profit Factor: {base_summary['profit_factor']}",
            f"- Sharpe: {base_summary['sharpe']}",
            f"- DSR: {base_summary['dsr']}",
            "",
            "## Filtered (TRENDING_UP+DOWN)",
            f"- Trades: {filtered_summary['trade_count']}",
            f"- Net profit: {filtered_summary['net_profit']:.2f}",
            f"- Profit Factor: {filtered_summary['profit_factor']}",
            f"- Sharpe: {filtered_summary['sharpe']}",
            f"- DSR: {filtered_summary['dsr']}",
            f"- Skipped by regime: {filtered_summary['skipped_regime']}",
            "",
            "## Delta",
            f"- Net profit: {delta['net_profit_pct']}%",
            f"- Sharpe: {delta['sharpe_pct']}%",
            f"- DSR: {delta['dsr_pct']}%",
        ]
        md_path = out_dir / "benchmark.md"
        md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

        print(f"Reports: {json_path}, {md_path}")

        # Regression guard: filtered must be >= baseline on net profit
        if not args.no_fail_on_regression:
            base_net = float(base_summary["net_profit"] or 0)
            filtered_net = float(filtered_summary["net_profit"] or 0)
            if filtered_net < base_net:
                print(f"REGRESSION: filtered net ({filtered_net:.2f}) < baseline ({base_net:.2f})")
                return 1

        return 0
    finally:
        platform.close()


if __name__ == "__main__":
    raise SystemExit(main())