"""بررسی هم‌خوانی config/live.json, config/phase.json, config/settings.json"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    path = ROOT / "config" / name
    if not path.exists():
        print(f"❌ فایل پیدا نشد: {path}")
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    live = load("live.json")
    phase = load("phase.json")
    settings = load("settings.json")

    auto = phase["automated_limited"]
    risk = settings["risk"]

    print("=== live.json ===")
    print(f"  instrument          : {live.get('instrument')}")
    print(f"  instruments         : {live.get('instruments')}")
    print(f"  timeframes          : {live.get('timeframes')}")
    print(f"  primary_timeframe   : {live.get('primary_timeframe')}")
    print(f"  interval_seconds    : {live.get('interval_seconds')}")
    print(f"  execute_orders      : {live.get('execute_orders')}")
    print(f"  min_score_threshold : {live.get('min_score_threshold')}")
    print(f"  max_signals_per_hour: {live.get('max_signals_per_hour')}")

    print()
    print("=== phase.json ===")
    print(f"  mode                : {phase.get('mode')}")
    print(f"  auto.enabled        : {auto.get('enabled')}")
    print(f"  auto.instruments    : {auto.get('instruments')}")
    print(f"  auto.timeframes     : {auto.get('timeframes')}")
    print(f"  auto.max_volume     : {auto.get('max_volume_per_order')}")
    print(f"  auto.max_open       : {auto.get('max_open_positions')}")
    print(f"  auto.max_daily      : {auto.get('max_daily_trades')}")
    print(f"  auto.risk_per_trade : {auto.get('risk_per_trade')}")
    print(f"  auto.daily_loss     : {auto.get('daily_loss_limit')}")
    print(f"  auto.drawdown_stop  : {auto.get('drawdown_stop')}")
    print(f"  auto.require_trig   : {auto.get('require_triggered_scenario')}")

    print()
    print("=== settings.json ===")
    print(f"  risk_per_trade      : {risk.get('risk_per_trade')}")
    print(f"  hard_cap            : {risk.get('hard_cap_risk_per_trade')}")
    print(f"  daily_loss_limit    : {risk.get('daily_loss_limit')}")
    print(f"  drawdown_stop       : {risk.get('drawdown_stop')}")
    print(f"  max_open_positions  : {risk.get('max_open_positions')}")
    print(f"  max_daily_trades    : {risk.get('max_daily_trades')}")

    print()
    print("=== هم‌خوانی ===")
    checks = [
        (
            "live.instruments == auto.instruments",
            live.get("instruments") == auto.get("instruments"),
        ),
        (
            "live.timeframes == auto.timeframes",
            live.get("timeframes") == auto.get("timeframes"),
        ),
        (
            "live.execute_orders == auto.enabled",
            bool(live.get("execute_orders")) == bool(auto.get("enabled")),
        ),
        (
            "auto.risk_per_trade == settings.risk_per_trade",
            str(auto.get("risk_per_trade")) == str(risk.get("risk_per_trade")),
        ),
        (
            "auto.daily_loss_limit == settings.daily_loss_limit",
            str(auto.get("daily_loss_limit")) == str(risk.get("daily_loss_limit")),
        ),
        (
            "auto.drawdown_stop == settings.drawdown_stop",
            str(auto.get("drawdown_stop")) == str(risk.get("drawdown_stop")),
        ),
        (
            "risk_per_trade <= hard_cap",
            float(risk.get("risk_per_trade", 0)) <= float(risk.get("hard_cap_risk_per_trade", 0)),
        ),
        (
            "drawdown_warn < drawdown_stop",
            float(risk.get("drawdown_warn", 0)) < float(risk.get("drawdown_stop", 1)),
        ),
        (
            "daily_loss_limit <= max_daily_loss_hard_cap",
            float(risk.get("daily_loss_limit", 0)) <= float(risk.get("max_daily_loss_hard_cap", 1)),
        ),
        (
            "drawdown_stop <= max_drawdown_hard_cap",
            float(risk.get("drawdown_stop", 0)) <= float(risk.get("max_drawdown_hard_cap", 1)),
        ),
    ]

    all_ok = True
    for name, ok in checks:
        mark = "✅" if ok else "❌"
        print(f"  {mark} {name}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("🎉 همه‌ی بررسی‌ها موفق. سه فایل هم‌خوان هستند.")
        return 0
    print("⚠️  برخی بررسی‌ها ناموفق‌اند. فایل‌ها را هم‌خوان کنید.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
