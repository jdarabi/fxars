# C:\FX\fix_live_required.py
"""Remove required=True from --instrument (read from config if absent)."""
from pathlib import Path
import shutil
import datetime

ROOT = Path(r'C:\FX')
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
BACKUP = ROOT / '.fix-backups' / f'live-required-{stamp}'
BACKUP.mkdir(parents=True, exist_ok=True)

path = ROOT / 'fxars/cli/main.py'
text = path.read_text(encoding='utf-8')

if 'def build_parser' not in text:
    print('ERROR: main.py corrupted')
    raise SystemExit(1)

# چک
if 'live.add_argument("--instrument", default=None' in text:
    print('[skip] --instrument already optional')
    raise SystemExit(0)

# جایگزینی
old = 'live.add_argument("--instrument", required=True)'
new = 'live.add_argument("--instrument", default=None, help="اگر نبود از config خوانده می‌شود")'

if old not in text:
    print('ERROR: anchor not found')
    # چاپ context
    for i, line in enumerate(text.split('\n')):
        if '--instrument' in line and 'live' in line:
            print(f'  {i+1}: {line}')
    raise SystemExit(1)

shutil.copy2(path, BACKUP / 'main.py')
print(f'Backup: {BACKUP / "main.py"}')

text = text.replace(old, new)
path.write_text(text, encoding='utf-8')
print(f'OK: patched')

import py_compile
try:
    py_compile.compile(str(path), doraise=True)
    print('syntax OK')
except py_compile.PyCompileError as exc:
    print('SYNTAX ERROR:', exc)
    raise SystemExit(1)