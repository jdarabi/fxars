"""اجرای کامل خط لوله دمو: داده → کیفیت → تحلیل → ریسک → بک‌تست → گزارش."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fxars.data.synthetic import generate_demo_bundle
from fxars.domain.enums import BacktestSegment
from fxars.platform import Platform
from fxars.research.report import write_report
from fxars.risk.account import demo_account


def main() -> int:
    platform = Platform()
    platform.bootstrap(create_users=False)
    data_dir = Path(platform.settings.data_dir)
    if not (data_dir / "EURUSD_H1.csv").exists():
        print("تولید داده دمو...")
        generate_demo_bundle(data_dir, instrument_ids=("EURUSD",))

    for instrument_id, source in (("EURUSD", "demo_feed"), ("DXY", "demo_ref")):
        result = platform.ingest_csv(
            data_dir / f"{instrument_id}_H1.csv", instrument_id=instrument_id,
            timeframe="H1", source_id=source,
        )
        quality = result.quality
        print(f"{instrument_id}: accepted={result.accepted} quarantined={result.quarantined} "
              f"verdict={quality.verdict if quality else '—'} stale={quality.stale if quality else '—'}")

    events = platform.ingest_events(data_dir / "economic_events.csv")
    print(f"economic events: {events}")

    analysis = platform.run_analysis("EURUSD", "H1")
    print(f"analysis: {analysis.run.run_id} status={analysis.run.status.value} "
          f"decision={analysis.decision.action.value} score={analysis.decision.score:+.3f} "
          f"scenario={analysis.scenario.scenario_id if analysis.scenario else None}")

    if analysis.scenario is not None:
        decision = platform.evaluate_risk(analysis.scenario.scenario_id, demo_account("10000", now=platform.clock()))
        print(f"risk: approved={decision.approved} size={decision.position_size} reason={decision.reason_code.value}")

    backtest = platform.run_backtest("EURUSD", "H1", segment=BacktestSegment.ALL)
    metrics = backtest.run.metrics
    print(f"backtest: {backtest.run.run_id} trades={metrics['trade_count']} net={metrics['net_profit']} "
          f"PF={metrics['profit_factor']} MDD%={metrics['max_drawdown_pct']}")
    reports = write_report(backtest.run, platform.settings.reports_dir)
    print(f"reports: {reports}")

    print(f"audit valid: {platform.audit_verify()['valid']}")
    platform.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
