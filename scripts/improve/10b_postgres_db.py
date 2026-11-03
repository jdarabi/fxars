from pathlib import Path
import sys

p = Path("C:/FX/fxars/storage/postgres.py")
text = p.read_text(encoding="utf-8")

if "FIX-10-USE-DIALECT" in text:
    print("[SKIP] postgres.py already patched")
else:
    # 1) import dialect
    old_import = "from contextlib import contextmanager\n"
    new_import = "from contextlib import contextmanager\n\nfrom fxars.storage.postgres_dialect import translate as _translate_sql\n"
    if old_import not in text:
        print("[FAIL] contextmanager import not found")
        sys.exit(1)
    text = text.replace(old_import, new_import)

    # 2) جایگزینی _translate_sql
    old_translate = '''    @staticmethod
    def _translate_sql(sql: str) -> str:
        """Translate SQLite '?' placeholders to psycopg '%s'."""
        return sql.replace("?", "%s")
'''
    new_translate = '''    @staticmethod
    def _translate_sql(sql: str) -> str:
        """FIX-10-USE-DIALECT: ترجمه کامل SQL (placeholder + INSERT OR REPLACE + PRAGMA + ...)."""
        return _translate_sql(sql)
'''
    if old_translate not in text:
        print("[FAIL] _translate_sql not found")
        sys.exit(1)
    text = text.replace(old_translate, new_translate)

    text = text.rstrip() + "\n\n# FIX-10-USE-DIALECT\n"
    p.write_text(text, encoding="utf-8")
    print("[PATCH 10b] postgres.py uses dialect")