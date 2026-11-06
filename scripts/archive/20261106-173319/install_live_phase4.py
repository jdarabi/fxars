# C:\FX\install_live_phase4.py
"""Phase 4: CLI fxars live."""
import datetime
import shutil
from pathlib import Path

ROOT = Path(r'C:\FX')
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
BACKUP = ROOT / '.fix-backups' / f'live-phase4-{stamp}'
BACKUP.mkdir(parents=True, exist_ok=True)


def backup(rel):
    src = ROOT / rel
    if not src.exists():
        return
    dst = BACKUP / rel.replace('\\', '__').replace('/', '__')
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def apply_patch(rel, old, new, description):
    print(f'  -> {description}')
    full = ROOT / rel
    text = full.read_text(encoding='utf-8')
    if 'cmd_live' in text and 'def cmd_live' in text:
        print(f'  [skip] {rel} already has cmd_live')
        return True
    if old not in text:
        print(f'  [WARN] {rel} anchor not found')
        return False
    backup(rel)
    full.write_text(text.replace(old, new), encoding='utf-8')
    print(f'  [patched] {rel}')
    return True


print('=== Phase 4: CLI fxars live ===')
print(f'Backup: {BACKUP}')

# 1) add cmd_live function before cmd_reconcile
old_anchor = 'def cmd_reconcile(args: argparse.Namespace) -> None:'
new_func = '''def cmd_live(args: argparse.Namespace) -> None:
    """FIX-LIVE-04: حلقهٔ تحلیل real-time + هشدار Telegram."""
    import logging
    from fxars.live.daemon import LiveDaemon, LiveDaemonConfig
    from fxars.live.mt5_feed import MT5Feed, MT5UnavailableError
    from fxars.live.notifier import TelegramConfig, TelegramNotifier

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )

    platform = _platform(args)
    feed = None
    try:
        try:
            feed = MT5Feed(source_id=args.source)
        except MT5UnavailableError as exc:
            print(f'خطا: MT5 موجود نیست: {exc}', file=sys.stderr)
            raise SystemExit(2)

        notifier = None
        tg_cfg = TelegramConfig.from_env()
        if tg_cfg is not None:
            try:
                notifier = TelegramNotifier(tg_cfg)
                print(f'Telegram notifier ready (chat_id={tg_cfg.chat_id})')
            except Exception as exc:
                print(f'Telegram disabled: {exc}', file=sys.stderr)
        else:
            print('Telegram disabled (set FXARS_TELEGRAM_TOKEN + FXARS_TELEGRAM_CHAT_ID)', file=sys.stderr)

        cfg = LiveDaemonConfig(
            instrument_id=args.instrument,
            timeframe=args.timeframe,
            interval_seconds=args.interval,
            history_bars=args.history,
            source_id=args.source,
            send_no_trade=args.send_no_trade,
            max_signals_per_hour=args.max_signals_per_hour,
        )
        daemon = LiveDaemon(
            config=cfg, platform=platform, feed=feed, notifier=notifier,
        )

        import signal as _signal
        def _handle_sigint(signum, frame):
            daemon.stop()
        try:
            _signal.signal(_signal.SIGINT, _handle_sigint)
        except Exception:
            pass

        print(f'Live daemon: {cfg.instrument_id}/{cfg.timeframe} every {cfg.interval_seconds}s')
        print('Press Ctrl+C to stop.')
        daemon.run(max_cycles=args.max_cycles)
        print(f'Stats: {daemon.stats.to_dict()}')
    finally:
        try:
            if feed is not None:
                feed.shutdown()
        except Exception:
            pass
        platform.close()


def cmd_reconcile(args: argparse.Namespace) -> None:'''

apply_patch('fxars/cli/main.py', old_anchor, new_func, 'cmd_live added')

# 2) add subparser
old_sub = '    ac = sub.add_parser("ac", help="اجرای آزمون‌های پذیرش")'
new_sub = '''    live = sub.add_parser("live", parents=[common], help="حلقهٔ تحلیل real-time + Telegram")
    live.add_argument("--instrument", required=True)
    live.add_argument("--timeframe", default="H1")
    live.add_argument("--interval", type=int, default=60, help="ثانیه بین هر تحلیل")
    live.add_argument("--history", type=int, default=500, help="تعداد کندل اولیه")
    live.add_argument("--source", default="mt5")
    live.add_argument("--max-cycles", dest="max_cycles", type=int, default=None)
    live.add_argument("--send-no-trade", dest="send_no_trade", action="store_true")
    live.add_argument("--max-signals-per-hour", dest="max_signals_per_hour", type=int, default=3)
    live.set_defaults(func=cmd_live)

    ac = sub.add_parser("ac", help="اجرای آزمون‌های پذیرش")'''

apply_patch('fxars/cli/main.py', old_sub, new_sub, 'live subparser added')

print()
print('=== Phase 4 done ===')
print()
print('Test:')
print('  python -m fxars live --help')
