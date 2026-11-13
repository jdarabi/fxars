"""FX-ARS interactive launcher (English menu) — run via FXARS.bat."""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LINE = "-" * 62


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _print_header() -> None:
    print()
    print(LINE)
    print("  FX-ARS  |  Forex Analysis & Decision Support System")
    print("  Phase MVP-1 - read-only; no orders are sent.")
    print(LINE)


def _pause() -> None:
    try:
        input("\nPress Enter to continue...")
    except (EOFError, KeyboardInterrupt):
        pass


def _ensure_users(platform) -> None:
    """Create demo users that do not exist; existing users are left untouched."""
    result = platform.bootstrap(
        admin_password=os.environ.get("FXARS_ADMIN_PASSWORD") or None,
        analyst_password=os.environ.get("FXARS_ANALYST_PASSWORD") or None,
    )
    for user in result.get("users", []):
        print(f"\nUser created: {user['username']} / {user['password']}"
              + (f"  |  TOTP: {user.get('totp_secret')}" if user.get("totp_secret") else ""))
    if result.get("users"):
        print("Store the password now; it is not kept in the code and will not be shown again.")


def _ensure_data(platform, *, force: bool = False) -> None:
    from fxars.data.synthetic import generate_demo_bundle

    data_dir = Path(platform.settings.data_dir)
    if force or not (data_dir / "EURUSD_H1.csv").exists():
        print("Generating deterministic demo data (~10 seconds)...")
        generate_demo_bundle(data_dir, instrument_ids=("EURUSD",))
    if platform.candles.count("EURUSD", "H1") == 0 or force:
        print("Loading data into the database...")
        for instrument_id, source in (("EURUSD", "demo_feed"), ("DXY", "demo_ref")):
            result = platform.ingest_csv(
                data_dir / f"{instrument_id}_H1.csv", instrument_id=instrument_id,
                timeframe="H1", source_id=source,
            )
            quality = result.quality
            print(f"  {instrument_id}: accepted={result.accepted} quarantined={result.quarantined} "
                  f"quality={quality.verdict if quality else '-'}")
        if (data_dir / "economic_events.csv").exists():
            count = platform.ingest_events(data_dir / "economic_events.csv")
            print(f"  Economic events: {count}")
        from fxars.risk.account import demo_account, parse_account_snapshot

        platform.accounts.save(parse_account_snapshot(demo_account("10000", now=platform.clock())))


def _open_platform(auto_seed: bool = True):
    from fxars.platform import Platform

    platform = Platform()
    _ensure_users(platform)
    if auto_seed:
        _ensure_data(platform)
    return platform


class DashboardServer:
    """Run API/dashboard in a background thread so the menu stays responsive."""

    def __init__(self, platform, host: str = "127.0.0.1", port: int = 0) -> None:
        self.platform = platform
        self.host = host
        self.base_port = port
        self.server = None
        self.thread: threading.Thread | None = None
        self.url = ""

    @property
    def running(self) -> bool:
        return self.server is not None

    def start(self) -> str:
        if self.running:
            return self.url
        from fxars.api.server import create_server

        last_error: Exception | None = None
        candidates = [0] if self.base_port == 0 else list(range(self.base_port, self.base_port + 12))
        for candidate in candidates:
            try:
                self.server = create_server(self.platform, self.host, candidate)
                break
            except OSError as exc:
                last_error = exc
        if self.server is None:
            raise RuntimeError(f"No free port found: {last_error}")
        self.url = f"http://{self.host}:{self.server.server_address[1]}/"
        self.thread = threading.Thread(target=self.server.serve_forever, name="fxars-api", daemon=True)
        self.thread.start()
        if not os.environ.get("FXARS_NO_BROWSER"):
            threading.Timer(1.2, lambda: webbrowser.open(self.url)).start()
        return self.url

    def stop(self) -> None:
        if self.server is None:
            return
        self.server.shutdown()
        self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)
        self.server = None
        self.thread = None
        try:
            self.platform.close()
        except Exception:
            pass


_DASHBOARD: DashboardServer | None = None


def _print_credentials(platform) -> None:
    admin = platform.users.get_by_username("admin")
    print("\nLogin accounts:")
    print("  Analyst: analyst   (no MFA)")
    print("  Admin:   admin     (6-digit code required)")
    print("  Demo passwords are shown once when the account is created (menu option 1 / init).")
    print("  Set FXARS_ADMIN_PASSWORD / FXARS_ANALYST_PASSWORD before creation to choose them.")
    if admin is not None and admin.totp_secret_enc:
        from fxars.identity.totp import totp

        secret = platform.identity.totp_secret(admin)
        print(f"  Current admin MFA code: {totp(secret)}  (valid for 30 seconds)")
        print("  New code: menu option 9 or command: python -m fxars auth code --username admin")


def _start_dashboard() -> None:
    global _DASHBOARD
    if _DASHBOARD is not None and _DASHBOARD.running:
        print(f"\nDashboard is already running: {_DASHBOARD.url}")
        if not os.environ.get("FXARS_NO_BROWSER"):
            webbrowser.open(_DASHBOARD.url)
        _print_credentials(_DASHBOARD.platform)
        return
    platform = _open_platform()
    port = int(os.environ.get("FXARS_PORT", "0") or "0")
    _DASHBOARD = DashboardServer(platform, port=port)
    url = _DASHBOARD.start()
    print(f"\nDashboard started: {url}")
    print("This menu stays open; use option 8 to stop the server and 0 to exit.")
    _print_credentials(platform)


def _stop_dashboard(*, quiet: bool = False) -> None:
    global _DASHBOARD
    if _DASHBOARD is None or not _DASHBOARD.running:
        if not quiet:
            print("\nNo dashboard is running.")
        return
    _DASHBOARD.stop()
    _DASHBOARD = None
    if not quiet:
        print("\nDashboard stopped.")


def _admin_code() -> None:
    from fxars.identity.totp import totp

    platform = _open_platform(auto_seed=False)
    try:
        admin = platform.users.get_by_username("admin")
        if admin is None or not admin.totp_secret_enc:
            print("\nAdmin user or its MFA was not found; run init first.")
            return
        secret = platform.identity.totp_secret(admin)
        code = totp(secret)
        remaining = 30 - int(time.time()) % 30
        print(f"\nCurrent MFA code: {code}  (valid for {remaining} seconds)")
    finally:
        platform.close()


def _analyze() -> None:
    platform = _open_platform()
    try:
        print("\nRunning analysis for EURUSD / H1 ...")
        result = platform.run_analysis("EURUSD", "H1")
        decision = result.decision
        print(f"\nRun: {result.run.run_id}")
        print(f"Status: {result.run.status.value}  |  Decision: {decision.action.value}  |  Score: {decision.score:+.3f}")
        print(f"Coverage: {decision.coverage:.0%}  |  Stability: {decision.stability:.0%}  |  Evidences: {len(result.evidences)}")
        if decision.no_trade_reason:
            print(f"NO TRADE reason: {decision.no_trade_reason}")
        for family, value in decision.family_scores.items():
            print(f"  {family:<12} {value:+.3f}")
        if result.scenario:
            scenario = result.scenario
            print(f"\nScenario: {scenario.scenario_id}  |  {scenario.direction.value}  |  {scenario.status.value}")
            print(f"  Entry: {scenario.entry_condition.get('type')} @ {scenario.entry_condition.get('level')}")
            print(f"  Stop: {scenario.stop_logic.get('level')}  |  Expiry: {scenario.expiry_at.isoformat()}")
        else:
            print(f"\nNo scenario created: {result.scenario_reason}")
        print("\nNext step: option 3 to evaluate risk for this scenario.")
    finally:
        platform.close()


def _risk() -> None:
    from fxars.risk.account import demo_account

    platform = _open_platform()
    try:
        live = [scenario for scenario in platform.scenarios.list(limit=20) if scenario.status.is_live]
        if not live:
            print("\nNo active scenario; run option 2 (analysis) first.")
            return
        scenario = live[0]
        decision = platform.evaluate_risk(scenario.scenario_id, demo_account("10000", now=platform.clock()))
        print(f"\nScenario: {scenario.scenario_id}  |  {scenario.direction.value}  |  {scenario.status.value}")
        print(f"Risk decision: {decision.decision_id}")
        print(f"Result: {'APPROVED' if decision.approved else 'REJECTED'}  |  Code: {decision.reason_code.value}")
        print(f"Size: {decision.position_size} lot  |  Risk: {decision.risk_amount} {decision.risk_currency}")
        if decision.checks_failed:
            print(f"Failed checks: {', '.join(decision.checks_failed)}")
        print(f"Reason: {decision.reason_detail}")
    finally:
        platform.close()


def _backtest() -> None:
    from fxars.research.report import write_report

    platform = _open_platform()
    try:
        print("\nRunning backtest (a few seconds)...")
        result = platform.research.run("EURUSD", "H1")
        metrics = result.run.metrics
        print(f"\nRun: {result.run.run_id}")
        for key in ("trade_count", "net_profit", "return_pct", "profit_factor", "win_rate",
                    "max_drawdown_pct", "sharpe", "sortino", "calmar"):
            print(f"  {key:<18} {metrics.get(key)}")
        print(f"  {'costs':<18} {metrics.get('costs')}")
        outputs = write_report(result.run, platform.settings.reports_dir)
        print("\nReports:")
        for name, path in outputs.items():
            print(f"  {name}: {path}")
    finally:
        platform.close()


def _audit() -> None:
    platform = _open_platform(auto_seed=False)
    try:
        result = platform.audit_verify()
        print(f"\nAudit chain: {'VALID' if result['valid'] else 'INCONSISTENT'}")
        print(f"  Records: {result['count']}  |  Chain head: {str(result.get('head'))[:16]}...")
        print(f"  Kill Switch: {'ACTIVE' if platform.killswitch.is_active() else 'INACTIVE'}")
        print(f"  Outbox pending: {platform.outbox.pending_count}")
    finally:
        platform.close()


def _tests() -> None:
    import unittest

    print("\nRunning tests (~75 seconds)...")
    suite = unittest.TestLoader().discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"\nResult: {result.testsRun} tests | errors={len(result.errors)} | failures={len(result.failures)}")


def _seed(force: bool = False) -> None:
    platform = _open_platform(auto_seed=False)
    try:
        _ensure_data(platform, force=force)
        print("\nDemo data is ready.")
        print(f"  EURUSD candles: {platform.candles.count('EURUSD', 'H1')}")
        print(f"  DXY candles:    {platform.candles.count('DXY', 'H1')}")
    finally:
        platform.close()


def menu() -> int:
    global _DASHBOARD
    _print_header()
    while True:
        status = f"\n  (Dashboard active: {_DASHBOARD.url})" if (_DASHBOARD and _DASHBOARD.running) else ""
        print(f"""
  1) Start dashboard and API  (auto port)
  2) Analyze EURUSD / H1
  3) Evaluate risk for the latest scenario
  4) Backtest and report
  5) Check audit and Kill Switch
  6) Run tests
  7) Prepare demo data
  8) Stop dashboard
  9) Show admin MFA code
  0) Exit{status}
""")
        try:
            choice = input("Your choice: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        try:
            if choice == "1":
                _start_dashboard()
            elif choice == "2":
                _analyze()
            elif choice == "3":
                _risk()
            elif choice == "4":
                _backtest()
            elif choice == "5":
                _audit()
            elif choice == "6":
                _tests()
            elif choice == "7":
                _seed()
            elif choice == "8":
                _stop_dashboard()
            elif choice == "9":
                _admin_code()
            elif choice == "0":
                break
            else:
                print("Invalid option.")
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
        except Exception as exc:  # clean message instead of a traceback
            print(f"\nError: {exc}")
        if choice in ("2", "3", "4", "5", "6", "7"):
            _pause()
    _stop_dashboard(quiet=True)
    print("\nGoodbye. Closing the window.")
    return 0


def main() -> int:
    _utf8_console()
    os.chdir(ROOT)
    if len(sys.argv) > 1:
        from fxars.cli.main import main as cli_main

        return cli_main(sys.argv[1:])
    return menu()


if __name__ == "__main__":
    raise SystemExit(main())
