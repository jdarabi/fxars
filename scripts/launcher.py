"""راه‌انداز تعاملی FX-ARS (منوی فارسی) — از طریق FXARS.bat اجرا می‌شود."""

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

ADMIN_PASSWORD = "AdminDemo12345!"
ANALYST_PASSWORD = "AnalystDemo123!"

LINE = "─" * 62


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _print_header() -> None:
    print()
    print(LINE)
    print("  FX-ARS  |  سامانه تحلیل و پشتیبانی تصمیم معاملات فارکس")
    print("  فاز MVP-1 — فقط‌خواندنی؛ هیچ سفارشی ارسال نمی‌شود.")
    print(LINE)


def _pause() -> None:
    try:
        input("\nبرای ادامه Enter بزنید...")
    except (EOFError, KeyboardInterrupt):
        pass


def _ensure_users(platform) -> None:
    """ساخت کاربران دمویی که وجود ندارند؛ کاربران موجود دست‌نخورده می‌مانند."""
    result = platform.bootstrap(admin_password=ADMIN_PASSWORD, analyst_password=ANALYST_PASSWORD)
    for user in result.get("users", []):
        print(f"\nکاربر ساخته شد: {user['username']} / {user['password']}"
              + (f"  |  TOTP: {user.get('totp_secret')}" if user.get("totp_secret") else ""))


def _ensure_data(platform, *, force: bool = False) -> None:
    from fxars.data.synthetic import generate_demo_bundle

    data_dir = Path(platform.settings.data_dir)
    if force or not (data_dir / "EURUSD_H1.csv").exists():
        print("در حال تولید داده دمو قطعی (حدود ۱۰ ثانیه)...")
        generate_demo_bundle(data_dir, instrument_ids=("EURUSD",))
    if platform.candles.count("EURUSD", "H1") == 0 or force:
        print("در حال ورود داده به پایگاه داده...")
        for instrument_id, source in (("EURUSD", "demo_feed"), ("DXY", "demo_ref")):
            result = platform.ingest_csv(
                data_dir / f"{instrument_id}_H1.csv", instrument_id=instrument_id,
                timeframe="H1", source_id=source,
            )
            quality = result.quality
            print(f"  {instrument_id}: پذیرفته={result.accepted} قرنطینه={result.quarantined} "
                  f"کیفیت={quality.verdict if quality else '—'}")
        if (data_dir / "economic_events.csv").exists():
            count = platform.ingest_events(data_dir / "economic_events.csv")
            print(f"  رویدادهای اقتصادی: {count}")
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
    """اجرای API/داشبورد در رشته پس‌زمینه تا منو قفل نشود."""

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
            raise RuntimeError(f"هیچ پورت آزادی پیدا نشد: {last_error}")
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
    print("\nاطلاعات ورود:")
    print("  تحلیل‌گر: analyst / AnalystDemo123!   (بدون MFA)")
    print("  مدیر:     admin / AdminDemo12345!   (نیازمند کد ۶ رقمی)")
    if admin is not None and admin.totp_secret_enc:
        from fxars.identity.totp import totp

        secret = platform.identity.totp_secret(admin)
        print(f"  کد MFA فعلی مدیر: {totp(secret)}  (تا ۳۰ ثانیه معتبر است)")
        print("  کد جدید: گزینه ۹ منو یا دستور: python -m fxars auth code --username admin")


def _start_dashboard() -> None:
    global _DASHBOARD
    if _DASHBOARD is not None and _DASHBOARD.running:
        print(f"\nداشبورد از قبل فعال است: {_DASHBOARD.url}")
        if not os.environ.get("FXARS_NO_BROWSER"):
            webbrowser.open(_DASHBOARD.url)
        _print_credentials(_DASHBOARD.platform)
        return
    platform = _open_platform()
    port = int(os.environ.get("FXARS_PORT", "0") or "0")
    _DASHBOARD = DashboardServer(platform, port=port)
    url = _DASHBOARD.start()
    print(f"\nداشبورد بالا آمد: {url}")
    print("این منو باز می‌ماند؛ برای توقف سرور گزینه ۸ و برای خروج گزینه ۰ را بزنید.")
    _print_credentials(platform)


def _stop_dashboard(*, quiet: bool = False) -> None:
    global _DASHBOARD
    if _DASHBOARD is None or not _DASHBOARD.running:
        if not quiet:
            print("\nداشبوردی در حال اجرا نیست.")
        return
    _DASHBOARD.stop()
    _DASHBOARD = None
    if not quiet:
        print("\nداشبورد متوقف شد.")


def _admin_code() -> None:
    from fxars.identity.totp import totp

    platform = _open_platform(auto_seed=False)
    try:
        admin = platform.users.get_by_username("admin")
        if admin is None or not admin.totp_secret_enc:
            print("\nکاربر admin یا MFA آن یافت نشد؛ ابتدا init را اجرا کنید.")
            return
        secret = platform.identity.totp_secret(admin)
        code = totp(secret)
        remaining = 30 - int(time.time()) % 30
        print(f"\nکد MFA فعلی: {code}  (تا {remaining} ثانیه معتبر است)")
    finally:
        platform.close()


def _analyze() -> None:
    platform = _open_platform()
    try:
        print("\nدر حال اجرای تحلیل EURUSD / H1 ...")
        result = platform.run_analysis("EURUSD", "H1")
        decision = result.decision
        print(f"\nاجرا: {result.run.run_id}")
        print(f"وضعیت: {result.run.status.value}  |  تصمیم: {decision.action.value}  |  امتیاز: {decision.score:+.3f}")
        print(f"پوشش: {decision.coverage:.0%}  |  پایداری: {decision.stability:.0%}  |  شواهد: {len(result.evidences)}")
        if decision.no_trade_reason:
            print(f"دلیل NO TRADE: {decision.no_trade_reason}")
        for family, value in decision.family_scores.items():
            print(f"  {family:<12} {value:+.3f}")
        if result.scenario:
            scenario = result.scenario
            print(f"\nسناریو: {scenario.scenario_id}  |  {scenario.direction.value}  |  {scenario.status.value}")
            print(f"  ورود: {scenario.entry_condition.get('type')} @ {scenario.entry_condition.get('level')}")
            print(f"  حد ضرر: {scenario.stop_logic.get('level')}  |  انقضا: {scenario.expiry_at.isoformat()}")
        else:
            print(f"\nسناریویی ساخته نشد: {result.scenario_reason}")
        print("\nگام بعدی: گزینه ۳ برای ارزیابی ریسک همین سناریو.")
    finally:
        platform.close()


def _risk() -> None:
    from fxars.risk.account import demo_account

    platform = _open_platform()
    try:
        live = [scenario for scenario in platform.scenarios.list(limit=20) if scenario.status.is_live]
        if not live:
            print("\nسناریوی فعالی وجود ندارد؛ ابتدا گزینه ۲ (تحلیل) را اجرا کنید.")
            return
        scenario = live[0]
        decision = platform.evaluate_risk(scenario.scenario_id, demo_account("10000", now=platform.clock()))
        print(f"\nسناریو: {scenario.scenario_id}  |  {scenario.direction.value}  |  {scenario.status.value}")
        print(f"تصمیم ریسک: {decision.decision_id}")
        print(f"نتیجه: {'تأیید' if decision.approved else 'رد'}  |  کد: {decision.reason_code.value}")
        print(f"حجم: {decision.position_size} lot  |  ریسک: {decision.risk_amount} {decision.risk_currency}")
        if decision.checks_failed:
            print(f"کنترل‌های ردشده: {', '.join(decision.checks_failed)}")
        print(f"دلیل: {decision.reason_detail}")
    finally:
        platform.close()


def _backtest() -> None:
    from fxars.research.report import write_report

    platform = _open_platform()
    try:
        print("\nدر حال اجرای بک‌تست (چند ثانیه)...")
        result = platform.research.run("EURUSD", "H1")
        metrics = result.run.metrics
        print(f"\nاجرا: {result.run.run_id}")
        for key in ("trade_count", "net_profit", "return_pct", "profit_factor", "win_rate",
                    "max_drawdown_pct", "sharpe", "sortino", "calmar"):
            print(f"  {key:<18} {metrics.get(key)}")
        print(f"  هزینه‌ها        {metrics.get('costs')}")
        outputs = write_report(result.run, platform.settings.reports_dir)
        print("\nگزارش‌ها:")
        for name, path in outputs.items():
            print(f"  {name}: {path}")
    finally:
        platform.close()


def _audit() -> None:
    platform = _open_platform(auto_seed=False)
    try:
        result = platform.audit_verify()
        print(f"\nزنجیره ممیزی: {'معتبر' if result['valid'] else 'ناسازگار'}")
        print(f"  تعداد رکورد: {result['count']}  |  سر زنجیره: {str(result.get('head'))[:16]}...")
        print(f"  Kill Switch: {'فعال' if platform.killswitch.is_active() else 'غیرفعال'}")
        print(f"  Outbox در انتظار: {platform.outbox.pending_count}")
    finally:
        platform.close()


def _tests() -> None:
    import unittest

    print("\nاجرای آزمون‌ها (حدود ۷۵ ثانیه)...")
    suite = unittest.TestLoader().discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"\nنتیجه: {result.testsRun} آزمون | خطا={len(result.errors)} | شکست={len(result.failures)}")


def _seed(force: bool = False) -> None:
    platform = _open_platform(auto_seed=False)
    try:
        _ensure_data(platform, force=force)
        print("\nداده دمو آماده است.")
        print(f"  کندل EURUSD: {platform.candles.count('EURUSD', 'H1')}")
        print(f"  کندل DXY:    {platform.candles.count('DXY', 'H1')}")
    finally:
        platform.close()


def menu() -> int:
    global _DASHBOARD
    _print_header()
    while True:
        status = f"\n  (داشبورد فعال: {_DASHBOARD.url})" if (_DASHBOARD and _DASHBOARD.running) else ""
        print(f"""
  1) اجرای داشبورد و API  (پورت خودکار)
  2) تحلیل EURUSD / H1
  3) ارزیابی ریسک آخرین سناریو
  4) بک‌تست و گزارش
  5) بررسی ممیزی و Kill Switch
  6) اجرای آزمون‌ها
  7) آماده‌سازی داده دمو
  8) توقف داشبورد
  9) نمایش کد MFA مدیر
  0) خروج{status}
""")
        try:
            choice = input("انتخاب شما: ").strip()
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
                print("گزینه نامعتبر است.")
        except KeyboardInterrupt:
            print("\nعملیات متوقف شد.")
        except Exception as exc:  # پیام تمیز به‌جای Traceback
            print(f"\nخطا: {exc}")
        if choice in ("2", "3", "4", "5", "6", "7"):
            _pause()
    _stop_dashboard(quiet=True)
    print("\nخداحافظ. پنجره بسته می‌شود.")
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
