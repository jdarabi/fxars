"""CLI سامانه FX-ARS."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from fxars.analysis.modules import module_specs
from fxars.config.settings import Settings
from fxars.core.timeutil import parse_ts, utcnow
from fxars.data.synthetic import generate_demo_bundle
from fxars.domain.enums import BacktestSegment, OrderStatus, Role, ScenarioStatus
from fxars.platform import Platform
from fxars.research.report import write_report
from fxars.risk.account import demo_account
from fxars.version import CODE_VERSION, DOCUMENT_ID


def _platform(args: argparse.Namespace) -> Platform:
    settings = Settings.load(getattr(args, "config", None))
    if getattr(args, "db", None):
        settings = replace(settings, db_path=args.db)
    platform = Platform(settings)
    platform.bootstrap(create_users=False) if not getattr(args, "no_seed", False) else None
    return platform


def _print_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> None:
    if not rows:
        print("(داده‌ای موجود نیست)")
        return
    widths = []
    for key, title in columns:
        widths.append(max(len(title), max(len(str(row.get(key, ""))) for row in rows)))
    header = " | ".join(title.ljust(width) for (_, title), width in zip(columns, widths))
    print(header)
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(str(row.get(key, "")).ljust(width) for (key, _), width in zip(columns, widths)))


def cmd_init(args: argparse.Namespace) -> None:
    platform = _platform(args)
    result = platform.bootstrap(admin_password=args.admin_password, analyst_password=args.analyst_password,
                                create_users=not args.no_users)
    print(f"پایگاه داده آماده است: {platform.settings.db_path}")
    print(f"نمادهای ثبت‌شده: {result['instruments']}")
    for user in result.get("users", []):
        print(f"کاربر {user['username']}: رمز={user.get('password')}  MFA={user.get('totp_secret') or '—'}")
    platform.close()


def cmd_seed(args: argparse.Namespace) -> None:
    platform = _platform(args)
    data_dir = Path(args.data_dir or platform.settings.data_dir)
    print("تولید داده دمو (قطعی)...")
    bundle = generate_demo_bundle(data_dir, instrument_ids=("EURUSD",), bars=args.bars, seed=args.seed)
    for instrument_id, info in bundle["candles"].items():  # type: ignore[union-attr]
        print(f"کندل {instrument_id}: {info['count']} — {info['first']} تا {info['last']}")
    for instrument_id in ("EURUSD",):
        result = platform.ingest_csv(data_dir / f"{instrument_id}_H1.csv", instrument_id=instrument_id,
                                     timeframe="H1", source_id="demo_feed")
        print(f"ورود {instrument_id}: پذیرفته={result.accepted} قرنطینه={result.quarantined} کیفیت={result.quality.verdict if result.quality else '—'}")
    reference = platform.ingest_csv(data_dir / "DXY_H1.csv", instrument_id="DXY", timeframe="H1", source_id="demo_ref")
    print(f"ورود DXY: پذیرفته={reference.accepted} کیفیت={reference.quality.verdict if reference.quality else '—'}")
    events = platform.ingest_events(data_dir / "economic_events.csv")
    print(f"رویدادهای اقتصادی: {events}")
    from fxars.risk.account import parse_account_snapshot

    account = parse_account_snapshot(demo_account("10000", now=utcnow()))
    platform.accounts.save(account)
    print("داده دمو آماده است.")
    platform.close()


def cmd_ingest(args: argparse.Namespace) -> None:
    platform = _platform(args)
    result = platform.ingest_csv(args.file, instrument_id=args.instrument, timeframe=args.timeframe,
                                 source_id=args.source)
    print(json.dumps({
        "accepted": result.accepted, "quarantined": result.quarantined, "duplicates": result.duplicates,
        "revised": result.revised, "quality": result.quality.to_dict() if result.quality else None,
        "errors": result.errors[:5],
    }, ensure_ascii=False, indent=2))
    platform.close()


def cmd_analyze(args: argparse.Namespace) -> None:
    platform = _platform(args)
    as_of = parse_ts(args.as_of) if args.as_of else None
    result = platform.run_analysis(args.instrument, args.timeframe, as_of=as_of)
    payload = {
        "run_id": result.run.run_id,
        "status": result.run.status.value,
        "decision": result.decision.to_dict(),
        "scenario": result.scenario.to_dict() if result.scenario else None,
        "scenario_reason": result.scenario_reason,
        "evidence_count": len(result.evidences),
        "config_hash": result.run.config_hash,
        "data_snapshot_id": result.run.data_snapshot_id,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        decision = result.decision
        print(f"اجرا: {result.run.run_id}  وضعیت: {result.run.status.value}")
        print(f"تصمیم: {decision.action.value}  امتیاز: {decision.score:+.3f}  پوشش: {decision.coverage:.0%}  پایداری: {decision.stability:.0%}")
        if decision.no_trade_reason:
            print(f"دلیل NO TRADE: {decision.no_trade_reason}")
        for family, value in decision.family_scores.items():
            print(f"  {family}: {value:+.3f}")
        print(f"شواهد ذخیره‌شده: {len(result.evidences)}")
        if result.scenario:
            scenario = result.scenario
            print(f"سناریو: {scenario.scenario_id}  {scenario.direction.value}  {scenario.status.value}")
            print(f"  ورود: {scenario.entry_condition}")
            print(f"  حد ضرر: {scenario.stop_logic}")
            print(f"  اهداف: {scenario.target_logic}")
    platform.close()


def cmd_scenarios(args: argparse.Namespace) -> None:
    platform = _platform(args)
    if args.id:
        scenario = platform.scenarios.get(args.id)
        if args.evaluate:
            evaluation = platform.evaluate_scenario(args.id)
            scenario = evaluation.scenario
            print(f"ارزیابی: {evaluation.reason} → {scenario.status.value}")
        transitions = platform.scenarios.transitions(scenario.scenario_id)
        decision = platform.decisions.latest_for_scenario(scenario.scenario_id)
        print(json.dumps({
            "scenario": scenario.to_dict(),
            "transitions": [transition.to_dict() for transition in transitions],
            "risk_decision": decision.to_dict() if decision else None,
        }, ensure_ascii=False, indent=2))
    else:
        scenarios = platform.scenarios.list(status=ScenarioStatus(args.status) if args.status else None, limit=args.limit)
        _print_table([{
            "id": scenario.scenario_id, "instrument": scenario.instrument_id, "dir": scenario.direction.value,
            "status": scenario.status.value, "expiry": scenario.expiry_at.isoformat(),
        } for scenario in scenarios], [("id", "شناسه"), ("instrument", "نماد"), ("dir", "جهت"), ("status", "وضعیت"), ("expiry", "انقضا")])
    platform.close()


def cmd_risk(args: argparse.Namespace) -> None:
    platform = _platform(args)
    account = demo_account(args.equity, now=utcnow())
    decision = platform.evaluate_risk(args.scenario, account)
    if args.json:
        print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"تصمیم ریسک: {decision.decision_id}")
        print(f"وضعیت: {'تأیید' if decision.approved else 'رد'}  کد: {decision.reason_code.value}")
        print(f"حجم پیشنهادی: {decision.position_size} lot — ریسک: {decision.risk_amount} {decision.risk_currency}")
        print(f"کنترل‌های ردشده: {', '.join(decision.checks_failed) or '—'}")
        print(f"دلیل: {decision.reason_detail}")
    platform.close()


def cmd_backtest(args: argparse.Namespace) -> None:
    platform = _platform(args)
    overrides = json.loads(args.overrides) if args.overrides else {}
    # P6-4: --allowed-regimes shortcut for the common case
    if getattr(args, "allowed_regimes", None):
        overrides["allowed_regimes"] = [r.strip() for r in args.allowed_regimes.split(",") if r.strip()]
    result = platform.run_backtest(args.instrument, args.timeframe, overrides=overrides,
                                   segment=BacktestSegment(args.segment))
    metrics = result.run.metrics
    print(f"بک‌تست: {result.run.run_id}")
    for key in ("trade_count", "net_profit", "return_pct", "profit_factor", "win_rate", "max_drawdown_pct",
                "sharpe", "sortino", "calmar", "expectancy"):
        print(f"  {key}: {metrics.get(key)}")
    print(f"  هزینه‌ها: {metrics.get('costs')}")
    print(f"  DSR: {metrics.get('deflated_sharpe')}")
    if args.report:
        outputs = write_report(result.run, platform.settings.reports_dir)
        print(f"گزارش‌ها: {outputs}")
    platform.close()


def cmd_walkforward(args: argparse.Namespace) -> None:
    platform = _platform(args)
    result = platform.walkforward.run(args.instrument, args.timeframe)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
    platform.close()


def cmd_pbo(args: argparse.Namespace) -> None:
    platform = _platform(args)
    variants = [
        {"stop_buffer_pips": 3}, {"stop_buffer_pips": 5}, {"stop_buffer_pips": 8},
        {"target_r_multiples": [2.0, 4.0]},
    ]
    result = platform.research.run_variants(args.instrument, args.timeframe, variants)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    platform.close()


def cmd_serve(args: argparse.Namespace) -> None:
    from fxars.api.server import serve

    platform = _platform(args)
    serve(platform, args.host, args.port)


def cmd_audit(args: argparse.Namespace) -> None:
    platform = _platform(args)
    if args.action == "verify":
        print(json.dumps(platform.audit_verify(), ensure_ascii=False, indent=2))
    else:
        entries = platform.audit.list_entries(limit=args.limit)
        _print_table([{
            "seq": entry.seq, "time": entry.occurred_at.isoformat(), "actor": entry.actor,
            "action": entry.action, "entity": f"{entry.entity_type}:{entry.entity_id}",
        } for entry in entries], [("seq", "#"), ("time", "زمان"), ("actor", "کاربر"), ("action", "عملیات"), ("entity", "موجودیت")])
    platform.close()


def cmd_killswitch(args: argparse.Namespace) -> None:
    platform = _platform(args)
    if args.action == "status":
        print(json.dumps(platform.kill_switch_status(), ensure_ascii=False, indent=2))
    else:
        status = platform.set_kill_switch(args.action == "on", actor=args.actor, reason=args.reason)
        print(json.dumps(status, ensure_ascii=False, indent=2))
    platform.close()


def cmd_users(args: argparse.Namespace) -> None:
    platform = _platform(args)
    if args.action == "list":
        _print_table([{"username": user.username, "role": user.role.value, "active": user.active,
                       "mfa": bool(user.totp_secret_enc), "tenant": user.tenant_id}
                      for user in platform.identity.list_users()],
                     [("username", "کاربر"), ("role", "نقش"), ("active", "فعال"), ("mfa", "MFA"), ("tenant", "مستاجر")])
    else:
        password = args.password or getpass.getpass("رمز عبور: ")
        user, secret = platform.identity.create_user(args.username, Role(args.role), password,
                                                     totp_enabled=args.mfa, actor=args.actor)
        print(json.dumps({"user_id": user.user_id, "username": user.username, "role": user.role.value,
                          "totp_secret": secret}, ensure_ascii=False, indent=2))
    platform.close()


def cmd_auth_code(args: argparse.Namespace) -> None:
    from fxars.identity.totp import totp

    platform = _platform(args)
    user = platform.users.get_by_username(args.username)
    if user is None:
        print("کاربر یافت نشد.", file=sys.stderr)
        raise SystemExit(2)
    secret = platform.identity.totp_secret(user)
    if secret is None:
        print("برای این کاربر MFA پیکربندی نشده است.", file=sys.stderr)
        raise SystemExit(2)
    print(totp(secret))
    platform.close()


def cmd_reconcile(args: argparse.Namespace) -> None:
    """P6-3: تطبیق سفارش‌های UNKNOWN با Broker."""
    from fxars.execution.reconciliation import ReconciliationService

    platform = _platform(args)
    try:
        svc = ReconciliationService(
            orders=platform.orders,
            broker=platform.execution.broker,
            audit=platform.audit,
            outbox=platform.outbox,
            clock=platform.clock,
        )
        results = svc.reconcile_all(actor=args.actor)
        if not results:
            print("(سفارشی در وضعیت UNKNOWN برای تطبیق یافت نشد)")
        else:
            for r in results:
                print(f"  {r.intent_id}: {r.from_status.value} → {r.to_status.value} ({r.reason})")
        print(f"تعداد تطبیق‌شده: {len(results)}")
    finally:
        platform.close()


def cmd_orders(args: argparse.Namespace) -> None:
    """P6-3: مدیریت سفارش‌ها."""
    platform = _platform(args)
    try:
        if args.action == "list":
            if args.status:
                try:
                    status = OrderStatus(args.status.upper())
                except ValueError:
                    print(f"وضعیت نامعتبر: {args.status}. مقادیر مجاز: {[s.value for s in OrderStatus]}")
                    return
                items = platform.orders.list_intents_by_status(status, limit=args.limit)
            else:
                items = []
                for st in OrderStatus:
                    items.extend(platform.orders.list_intents_by_status(st, limit=args.limit))
            if not items:
                print("(سفارشی یافت نشد)")
            else:
                rows = [{
                    "id": item.intent_id,
                    "status": item.status.value,
                    "client": item.client_order_id,
                    "instrument": item.instrument_id,
                    "side": item.side.value,
                    "volume": str(item.volume),
                    "created": item.created_at.isoformat(),
                } for item in items[:args.limit]]
                _print_table(rows, [
                    ("id", "شناسه"), ("status", "وضعیت"), ("client", "client_order_id"),
                    ("instrument", "نماد"), ("side", "جهت"), ("volume", "حجم"), ("created", "ایجاد"),
                ])
        elif args.action == "show":
            if not args.intent_id:
                print("--intent-id الزامی است برای show", file=sys.stderr)
                raise SystemExit(2)
            item = platform.orders.get_intent(args.intent_id)
            if item is None:
                print(f"سفارش {args.intent_id} یافت نشد")
            else:
                print(json.dumps(item.to_dict(), ensure_ascii=False, indent=2))
    finally:
        platform.close()


def cmd_ac(args: argparse.Namespace) -> None:
    import unittest

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName("tests.test_acceptance")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


def cmd_selftest(args: argparse.Namespace) -> None:
    import unittest

    loader = unittest.TestLoader()
    suite = loader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


def cmd_meta(args: argparse.Namespace) -> None:
    print(json.dumps({
        "document_id": DOCUMENT_ID, "code_version": CODE_VERSION,
        "modules": module_specs(),
    }, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", help="مسیر پایگاه داده SQLite")
    common.add_argument("--config", help="مسیر فایل پیکربندی JSON")
    common.add_argument("--no-seed", action="store_true", help="بدون ثبت نمادهای پیش‌فرض")

    parser = argparse.ArgumentParser(prog="fxars", description="FX-ARS — سامانه تحلیل و پشتیبانی تصمیم فارکس")
    parser.add_argument("--version", action="version", version=f"FX-ARS {CODE_VERSION} ({DOCUMENT_ID})")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", parents=[common], help="ساخت پایگاه داده و کاربران پایه")
    init.add_argument("--admin-password")
    init.add_argument("--analyst-password")
    init.add_argument("--no-users", action="store_true")
    init.set_defaults(func=cmd_init)

    seed = sub.add_parser("seed-demo", parents=[common], help="تولید و ورود داده دمو")
    seed.add_argument("--data-dir")
    seed.add_argument("--bars", type=int, default=4658)
    seed.add_argument("--seed", type=int, default=7)
    seed.set_defaults(func=cmd_seed)

    ingest = sub.add_parser("ingest", parents=[common], help="ورود CSV کندل")
    ingest.add_argument("--file", required=True)
    ingest.add_argument("--instrument", required=True)
    ingest.add_argument("--timeframe", default="H1")
    ingest.add_argument("--source", default="demo_feed")
    ingest.set_defaults(func=cmd_ingest)

    analyze = sub.add_parser("analyze", parents=[common], help="اجرای تحلیل")
    analyze.add_argument("--instrument", required=True)
    analyze.add_argument("--timeframe", default="H1")
    analyze.add_argument("--as-of")
    analyze.add_argument("--json", action="store_true")
    analyze.set_defaults(func=cmd_analyze)

    scenarios = sub.add_parser("scenarios", parents=[common], help="فهرست/جزئیات/ارزیابی سناریو")
    scenarios.add_argument("--id")
    scenarios.add_argument("--status")
    scenarios.add_argument("--limit", type=int, default=20)
    scenarios.add_argument("--evaluate", action="store_true")
    scenarios.set_defaults(func=cmd_scenarios)

    risk = sub.add_parser("risk", parents=[common], help="ارزیابی ریسک سناریو")
    risk.add_argument("--scenario", required=True)
    risk.add_argument("--equity", default="10000")
    risk.add_argument("--json", action="store_true")
    risk.set_defaults(func=cmd_risk)

    backtest = sub.add_parser("backtest", parents=[common], help="اجرای بک‌تست")
    backtest.add_argument("--instrument", required=True)
    backtest.add_argument("--timeframe", default="H1")
    backtest.add_argument("--segment", default="ALL", choices=[item.value for item in BacktestSegment])
    backtest.add_argument("--overrides", help="JSON پارامترهای بازنویسی")
    backtest.add_argument(
        "--allowed-regimes", dest="allowed_regimes",
        help="فهرست رژیم‌های مجاز با کاما (مثلاً TRENDING_UP,TRENDING_DOWN)",
    )
    backtest.add_argument("--report", action="store_true")
    backtest.set_defaults(func=cmd_backtest)

    walk = sub.add_parser("walkforward", parents=[common], help="اعتبارسنجی Walk-forward")
    walk.add_argument("--instrument", required=True)
    walk.add_argument("--timeframe", default="H1")
    walk.set_defaults(func=cmd_walkforward)

    pbo = sub.add_parser("pbo", parents=[common], help="Probability of Backtest Overfitting")
    pbo.add_argument("--instrument", required=True)
    pbo.add_argument("--timeframe", default="H1")
    pbo.set_defaults(func=cmd_pbo)

    serve = sub.add_parser("serve", parents=[common], help="اجرای API و داشبورد")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.set_defaults(func=cmd_serve)

    audit = sub.add_parser("audit", parents=[common], help="ممیزی")
    audit.add_argument("action", choices=["verify", "list"])
    audit.add_argument("--limit", type=int, default=30)
    audit.set_defaults(func=cmd_audit)

    kill = sub.add_parser("killswitch", parents=[common], help="کلید توقف اضطراری")
    kill.add_argument("action", choices=["status", "on", "off"])
    kill.add_argument("--reason", default="دستور اپراتور")
    kill.add_argument("--actor", default="cli")
    kill.set_defaults(func=cmd_killswitch)

    users = sub.add_parser("users", parents=[common], help="مدیریت کاربران")
    users.add_argument("action", choices=["list", "create"])
    users.add_argument("--username")
    users.add_argument("--role", default="ANALYST", choices=[role.value for role in Role])
    users.add_argument("--password")
    users.add_argument("--mfa", action="store_true")
    users.add_argument("--actor", default="cli")
    users.set_defaults(func=cmd_users)

    code = sub.add_parser("auth", parents=[common], help="ابزارهای احراز هویت")
    code.add_argument("action", choices=["code"])
    code.add_argument("--username", default="admin")
    code.set_defaults(func=cmd_auth_code)

    reconcile = sub.add_parser("reconcile", parents=[common], help="تطبیق سفارش‌های UNKNOWN")
    reconcile.add_argument("--actor", default="cli")
    reconcile.set_defaults(func=cmd_reconcile)

    orders = sub.add_parser("orders", parents=[common], help="مدیریت سفارش‌ها")
    orders.add_argument("action", choices=["list", "show"])
    orders.add_argument("--status", help="فیلتر وضعیت")
    orders.add_argument("--limit", type=int, default=50)
    orders.add_argument("--intent-id", dest="intent_id")
    orders.set_defaults(func=cmd_orders)

    ac = sub.add_parser("ac", help="اجرای آزمون‌های پذیرش")
    ac.set_defaults(func=cmd_ac)

    selftest = sub.add_parser("selftest", help="اجرای کل آزمون‌ها")
    selftest.set_defaults(func=cmd_selftest)

    meta = sub.add_parser("modules", help="مشخصات ماژول‌های تحلیل")
    meta.set_defaults(func=cmd_meta)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # پیام تمیز برای CLI
        print(f"خطا: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())