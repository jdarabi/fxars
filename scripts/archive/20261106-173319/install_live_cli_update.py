# C:\FX\install_live_cli_update.py
"""Update CLI `live` to support --config + --timeframes + --schedule."""
from pathlib import Path
import shutil
import datetime

ROOT = Path(r'C:\FX')
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
BACKUP = ROOT / '.fix-backups' / f'live-cli-update-{stamp}'
BACKUP.mkdir(parents=True, exist_ok=True)

path = ROOT / 'fxars/cli/main.py'
text = path.read_text(encoding='utf-8')

# چک نسخه جدید
if 'FIX-LIVE-CLI-CONFIG' in text:
    print('[skip] CLI already updated')
    raise SystemExit(0)

old = '''def cmd_live(args: argparse.Namespace) -> None:
    """FIX-LIVE-04: حلقه تحلیل real-time + هشدار Telegram."""
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
'''

new = '''def cmd_live(args: argparse.Namespace) -> None:
    """FIX-LIVE-CLI-CONFIG: حلقه تحلیل real-time با config + multi-timeframe."""
    import logging
    from fxars.live.daemon import LiveDaemon, LiveDaemonConfig
    from fxars.live.mt5_feed import MT5Feed, MT5UnavailableError
    from fxars.live.notifier import TelegramConfig, TelegramNotifier
    from fxars.live.config import LiveConfig, ScheduleConfig

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )

    # 1) بارگذاری config از فایل (اگر داده شده)
    live_config = None
    if getattr(args, 'live_config', None):
        try:
            live_config = LiveConfig.load(args.live_config)
            print(f'Loaded config: {args.live_config}')
        except Exception as exc:
            print(f'خطا در بارگذاری config: {exc}', file=sys.stderr)
            raise SystemExit(2)

    # 2) override با CLI args
    instrument = args.instrument or (live_config.instrument if live_config else 'EURUSD')
    timeframes = None
    if getattr(args, 'timeframes', None):
        timeframes = [t.strip().upper() for t in args.timeframes.split(',') if t.strip()]
    elif live_config is not None:
        timeframes = list(live_config.timeframes)
    else:
        timeframes = [args.timeframe]

    primary_tf = args.timeframe or (live_config.primary_timeframe if live_config else 'H1')
    interval = args.interval or (live_config.interval_seconds if live_config else 60)
    history = args.history or (live_config.history_bars if live_config else 500)
    source = args.source or (live_config.source_id if live_config else 'mt5')
    send_no_trade = args.send_no_trade or (live_config.send_no_trade if live_config else False)
    max_signals = args.max_signals_per_hour or (live_config.max_signals_per_hour if live_config else 3)

    # 3) schedule
    schedule = None
    if getattr(args, 'schedule_mode', None):
        schedule = ScheduleConfig(
            mode=args.schedule_mode,
            minute_offsets=[int(m.strip()) for m in (args.schedule_minutes or '0,15,30,45').split(',')],
            active_hours_utc=[
                int(h.strip()) for h in (args.schedule_hours or ','.join(str(h) for h in range(24))).split(',')
            ],
            active_days=(args.schedule_days or 'Mon,Tue,Wed,Thu,Fri').split(','),
        )
    elif live_config is not None:
        schedule = live_config.schedule

    platform = _platform(args)
    feed = None
    try:
        try:
            feed = MT5Feed(source_id=source)
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
            instrument_id=instrument,
            timeframe=primary_tf,
            timeframes=timeframes,
            interval_seconds=int(interval),
            history_bars=int(history),
            source_id=source,
            send_no_trade=bool(send_no_trade),
            max_signals_per_hour=int(max_signals),
            schedule=schedule,
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

        print(f'Live daemon: {cfg.instrument_id} {timeframes} every {cfg.interval_seconds}s')
        if schedule:
            print(f'  schedule: mode={schedule.mode}, days={schedule.active_days}, '
                  f'hours={schedule.active_hours_utc[:3]}..., minutes={schedule.minute_offsets}')
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
'''

if old not in text:
    print('ERROR: cmd_live anchor not found')
    print('Looking for: def cmd_live')
    raise SystemExit(1)

shutil.copy2(path, BACKUP / 'main.py')
print(f'Backup: {BACKUP / "main.py"}')

text = text.replace(old, new)

# آپدیت subparser
old_sub = '''    live = sub.add_parser("live", parents=[common], help="حلقه تحلیل real-time + Telegram")
    live.add_argument("--instrument", required=True)
    live.add_argument("--timeframe", default="H1")
    live.add_argument("--interval", type=int, default=60, help="ثانیه بین هر تحلیل")
    live.add_argument("--history", type=int, default=500, help="تعداد کندل اولیه")
    live.add_argument("--source", default="mt5")
    live.add_argument("--max-cycles", dest="max_cycles", type=int, default=None)
    live.add_argument("--send-no-trade", dest="send_no_trade", action="store_true")
    live.add_argument("--max-signals-per-hour", dest="max_signals_per_hour", type=int, default=3)
    live.set_defaults(func=cmd_live)'''

new_sub = '''    live = sub.add_parser("live", parents=[common], help="حلقه تحلیل real-time + Telegram")
    live.add_argument("--live-config", dest="live_config", help="مسیر config JSON (مثلاً config/live.json)")
    live.add_argument("--instrument", default=None, help="نماد (اگر نبود از config)")
    live.add_argument("--timeframe", default=None, help="تایم‌فریم اصلی (اگر نبود از config)")
    live.add_argument("--timeframes", default=None, help="چند تایم‌فریم با کاما (مثلاً M15,H1,H4)")
    live.add_argument("--interval", type=int, default=None, help="ثانیه بین هر تحلیل")
    live.add_argument("--history", type=int, default=None, help="تعداد کندل اولیه")
    live.add_argument("--source", default=None)
    live.add_argument("--max-cycles", dest="max_cycles", type=int, default=None)
    live.add_argument("--send-no-trade", dest="send_no_trade", action="store_true")
    live.add_argument("--max-signals-per-hour", dest="max_signals_per_hour", type=int, default=None)
    live.add_argument("--schedule-mode", dest="schedule_mode", choices=["always", "offsets"], default=None)
    live.add_argument("--schedule-minutes", dest="schedule_minutes", default=None, help="مثلاً 0,15,30,45")
    live.add_argument("--schedule-hours", dest="schedule_hours", default=None, help="ساعت‌های UTC با کاما")
    live.add_argument("--schedule-days", dest="schedule_days", default=None, help="روزها با کاما")
    live.set_defaults(func=cmd_live)'''

if old_sub not in text:
    print('WARN: subparser block not found (maybe already updated)')
else:
    text = text.replace(old_sub, new_sub)
    print('  [patched] subparser')

text += '\\n\\n# FIX-LIVE-CLI-CONFIG\\n'
path.write_text(text, encoding='utf-8')
print('OK: CLI updated')

import py_compile
try:
    py_compile.compile(str(path), doraise=True)
    print('syntax OK')
except py_compile.PyCompileError as exc:
    print('SYNTAX ERROR:', exc)
    raise SystemExit(1)