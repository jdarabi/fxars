# C:\FX\fix_live_subparser.py
from pathlib import Path
import py_compile

path = Path(r'C:\FX\fxars\cli\main.py')
text = path.read_text(encoding='utf-8')

if 'def cmd_live(' not in text:
    print('ERROR: cmd_live function missing')
    raise SystemExit(1)

if 'sub.add_parser("live"' in text:
    print('subparser already exists')
    raise SystemExit(0)

anchor = '    ac = sub.add_parser("ac", help="اجرای آزمون‌های پذیرش")'
if anchor not in text:
    print('ERROR: ac anchor not found')
    raise SystemExit(1)

live_sub = '''    live = sub.add_parser("live", parents=[common], help="حلقه تحلیل real-time + Telegram")
    live.add_argument("--instrument", required=True)
    live.add_argument("--timeframe", default="H1")
    live.add_argument("--interval", type=int, default=60)
    live.add_argument("--history", type=int, default=500)
    live.add_argument("--source", default="mt5")
    live.add_argument("--max-cycles", dest="max_cycles", type=int, default=None)
    live.add_argument("--send-no-trade", dest="send_no_trade", action="store_true")
    live.add_argument("--max-signals-per-hour", dest="max_signals_per_hour", type=int, default=3)
    live.set_defaults(func=cmd_live)

    ac = sub.add_parser("ac", help="اجرای آزمون‌های پذیرش")'''

new_text = text.replace(anchor, live_sub)
path.write_text(new_text, encoding='utf-8')
print('OK: subparser added')

try:
    py_compile.compile(str(path), doraise=True)
    print('syntax OK')
except py_compile.PyCompileError as exc:
    print('SYNTAX ERROR:', exc)
    raise SystemExit(1)