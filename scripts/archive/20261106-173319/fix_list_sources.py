# C:\FX\fix_list_sources.py
"""Fix InstrumentRepository.list_sources — priority is in payload, not a column."""
from pathlib import Path
import shutil
import datetime

ROOT = Path(r'C:\FX')
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
BACKUP = ROOT / '.fix-backups' / f'list-sources-fix-{stamp}'
BACKUP.mkdir(parents=True, exist_ok=True)

path = ROOT / 'fxars/storage/repositories.py'
if not path.exists():
    print('ERROR: repositories.py not found')
    raise SystemExit(1)

text = path.read_text(encoding='utf-8')

old = '''    def list_sources(self) -> list[DataSource]:
        return [DataSource(**_row_payload(row)) for row in self.db.query("SELECT payload FROM data_sources ORDER BY priority")]'''

new = '''    def list_sources(self) -> list[DataSource]:
        # FIX-SOURCES-ORDER: priority در payload است، نه ستون
        rows = list(self.db.query("SELECT payload FROM data_sources"))
        sources = [DataSource(**_row_payload(row)) for row in rows]
        sources.sort(key=lambda s: s.priority)
        return sources'''

if old not in text:
    if 'FIX-SOURCES-ORDER' in text:
        print('[skip] already patched')
        raise SystemExit(0)
    print('ERROR: anchor not found')
    raise SystemExit(1)

shutil.copy2(path, BACKUP / 'repositories.py')
print(f'Backup: {BACKUP / "repositories.py"}')

text = text.replace(old, new)
path.write_text(text, encoding='utf-8')
print('OK: list_sources patched')

import py_compile
try:
    py_compile.compile(str(path), doraise=True)
    print('syntax OK')
except py_compile.PyCompileError as exc:
    print('SYNTAX ERROR:', exc)
    raise SystemExit(1)
