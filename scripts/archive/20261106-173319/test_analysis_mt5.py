# C:\FX\test_analysis_mt5.py
from datetime import UTC, datetime

from fxars.platform import Platform

p = Platform()
p.bootstrap(create_users=False)

try:
    # 1) primary source
    primary = p.instruments.primary_source("EURUSD", "H1")
    print(f"primary_source: {primary}")

    # 2) آخرین کندل mt5
    c = p.candles.range("EURUSD", "H1", source_id="mt5", closed_only=True)
    if not c:
        print("ERROR: no mt5 candles")
        raise SystemExit(1)

    latest = c[-1]
    as_of = latest.available_at
    now = datetime.now(tz=UTC)

    print(f"latest_candle: {latest.open_time.isoformat()}")
    print(f"available_at : {as_of.isoformat()}")
    print(f"now          : {now.isoformat()}")
    print(f"gap_seconds  : {(now - as_of).total_seconds():.0f}")
    print()

    # 3) تحلیل
    result = p.run_analysis("EURUSD", "H1", as_of=as_of)
    print(f"run.status    : {result.run.status.value}")
    print(f"decision.action: {result.decision.action.value}")
    print(f"score         : {result.decision.score:+.3f}")
    print(f"coverage      : {result.decision.coverage:.0%}")
    print(f"stability     : {result.decision.stability:.0%}")
    print(f"no_trade_reason: {result.decision.no_trade_reason}")
    print()

    if result.decision.family_scores:
        print("family_scores:")
        for fam, sc in result.decision.family_scores.items():
            print(f"  {fam}: {sc:+.3f}")
    print()

    if result.scenario:
        s = result.scenario
        print(f"scenario: {s.scenario_id}")
        print(f"  direction: {s.direction.value}")
        print(f"  entry    : {s.entry_condition}")
        print(f"  stop     : {s.stop_logic}")
        print(f"  targets  : {s.target_logic}")
        print(f"  expiry   : {s.expiry_at.isoformat()}")
    else:
        print(f"no scenario: {result.scenario_reason}")
finally:
    p.close()
