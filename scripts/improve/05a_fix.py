from pathlib import Path
import sys

# ===========================================================================
# 1) schema.sql: افزودن ستون‌ها
# ===========================================================================
schema_p = Path('C:/FX/fxars/storage/schema.sql')
schema = schema_p.read_text(encoding='utf-8')

if 'dead_letter_at' in schema:
    print('[SKIP schema] dead_letter_at already present')
else:
    old = '''CREATE TABLE IF NOT EXISTS outbox (
    event_id       TEXT PRIMARY KEY,
    event_type     TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    occurred_at    TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    payload        TEXT NOT NULL,
    published_at   TEXT
);'''
    new = '''CREATE TABLE IF NOT EXISTS outbox (
    event_id       TEXT PRIMARY KEY,
    event_type     TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    occurred_at    TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    payload        TEXT NOT NULL,
    published_at   TEXT,
    attempts       INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT,
    dead_letter_at TEXT
);'''
    if old not in schema:
        print('[FAIL schema] table block not found')
        sys.exit(1)
    schema = schema.replace(old, new)
    schema_p.write_text(schema, encoding='utf-8')
    print('[PATCH schema] dead_letter columns added')

# ===========================================================================
# 2) db.py: _ensure_column برای outbox + متد helper
# ===========================================================================
db_p = Path('C:/FX/fxars/storage/db.py')
db = db_p.read_text(encoding='utf-8')

if '_ensure_column' not in db:
    old = '''    def migrate(self) -> None:
        script = SCHEMA_PATH.read_text(encoding="utf-8")
        # executescript خودش تراکنش را COMMIT می‌کند؛ بنابراین خارج از transaction صریح اجرا می‌شود.
        with self._lock:
            self._conn.executescript(script)
'''
    new = '''    def migrate(self) -> None:
        script = SCHEMA_PATH.read_text(encoding="utf-8")
        # executescript خودش تراکنش را COMMIT می‌کند؛ بنابراین خارج از transaction صریح اجرا می‌شود.
        with self._lock:
            self._conn.executescript(script)
            # FIX-09-OUTBOX-RETRY: افزودن ستون‌های جدید در صورت نبود
            self._ensure_column("outbox", "attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column("outbox", "last_error", "TEXT")
            self._ensure_column("outbox", "dead_letter_at", "TEXT")
'''
    if old not in db:
        print('[FAIL db.py] migrate anchor not found')
        sys.exit(1)
    db = db.replace(old, new)

    anchor = '''    def close(self) -> None:
        with self._lock:
            self._conn.close()
'''
    helper = '''    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        cols = [row["name"] for row in self.query(f"PRAGMA table_info({table})")]
        if column not in cols:
            self.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
'''
    if anchor not in db:
        print('[FAIL db.py] close anchor not found')
        sys.exit(1)
    db = db.replace(anchor, helper)
    db_p.write_text(db, encoding='utf-8')
    print('[PATCH db.py] _ensure_column added')
else:
    print('[SKIP db.py] _ensure_column already present')

# ===========================================================================
# 3) repositories.py: OutboxRepository بهبودها
# ===========================================================================
repo_p = Path('C:/FX/fxars/storage/repositories.py')
repo = repo_p.read_text(encoding='utf-8')

if 'def attempts_for' in repo:
    print('[SKIP repositories] attempts_for already present')
else:
    old_pending = '''    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM outbox WHERE published_at IS NULL ORDER BY occurred_at LIMIT ?", (limit,))
        return [
            {
                "event_id": row["event_id"], "event_type": row["event_type"], "schema_version": row["schema_version"],
                "occurred_at": row["occurred_at"], "correlation_id": row["correlation_id"], "payload": _load(row["payload"]),
                "published_at": row["published_at"],
            }
            for row in rows
        ]'''
    new_pending = '''    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM outbox WHERE published_at IS NULL AND dead_letter_at IS NULL "
            "ORDER BY occurred_at LIMIT ?",
            (limit,),
        )
        return [
            {
                "event_id": row["event_id"], "event_type": row["event_type"],
                "schema_version": row["schema_version"], "occurred_at": row["occurred_at"],
                "correlation_id": row["correlation_id"], "payload": _load(row["payload"]),
                "published_at": row["published_at"], "attempts": int(row["attempts"] or 0),
            }
            for row in rows
        ]

    def attempts_for(self, event_id: str) -> int:
        return int(self.db.scalar("SELECT attempts FROM outbox WHERE event_id=?", (event_id,)) or 0)

    def bump_attempt(self, event_id: str, *, last_error: str = "") -> None:
        self.db.execute(
            "UPDATE outbox SET attempts = attempts + 1, last_error=? WHERE event_id=?",
            (last_error, event_id),
        )

    def mark_dead_letter(self, event_id: str, when, *, reason: str = "") -> None:
        from fxars.core.timeutil import format_ts
        self.db.execute(
            "UPDATE outbox SET dead_letter_at=?, last_error=? WHERE event_id=?",
            (format_ts(when), reason, event_id),
        )

    def dead_letters(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM outbox WHERE dead_letter_at IS NOT NULL ORDER BY dead_letter_at LIMIT ?",
            (limit,),
        )
        return [
            {
                "event_id": row["event_id"], "event_type": row["event_type"],
                "dead_letter_at": row["dead_letter_at"], "last_error": row["last_error"],
                "attempts": int(row["attempts"] or 0),
            }
            for row in rows
        ]'''
    if old_pending not in repo:
        print('[FAIL repositories] old pending() not found')
        sys.exit(1)
    repo = repo.replace(old_pending, new_pending)
    repo_p.write_text(repo, encoding='utf-8')
    print('[PATCH repositories] pending/attempts/dead_letters added')

# ===========================================================================
# 4) outbox.py: publish_pending با retry/dead-letter
# ===========================================================================
ob_p = Path('C:/FX/fxars/audit/outbox.py')
ob = ob_p.read_text(encoding='utf-8')

if 'FIX-09-OUTBOX-RETRY' in ob:
    print('[SKIP outbox.py] already patched')
else:
    old = '''    def publish_pending(
        self,
        handlers: dict[str, Callable[[dict[str, Any]], None]],
        *,
        limit: int = 100,
    ) -> dict[str, int]:
        """پردازش رویدادها؛ خطای یک handler مانع بقیه نمی‌شود و رویداد منتشرنشده می‌ماند."""
        stats = {"published": 0, "failed": 0, "skipped": 0}
        for event in self.pending(limit):
            handler = handlers.get(event["event_type"])
            if handler is None:
                self.repo.mark_published(event["event_id"], utcnow())
                stats["skipped"] += 1
                continue
            try:
                handler(event)
            except FxarsError as exc:
                logger.warning("outbox handler failed", extra={"data": {"event": event["event_id"], "error": exc.code}})
                stats["failed"] += 1
                continue
            except Exception as exc:  # pragma: no cover - دفاعی
                logger.exception("outbox handler crashed", extra={"data": {"event": event["event_id"]}})
                stats["failed"] += 1
                continue
            self.repo.mark_published(event["event_id"], utcnow())
            stats["published"] += 1
        return stats'''
    new = '''    def publish_pending(
        self,
        handlers: dict[str, Callable[[dict[str, Any]], None]],
        *,
        limit: int = 100,
        max_attempts: int = 5,
    ) -> dict[str, int]:
        """FIX-09-OUTBOX-RETRY: پردازش با retry و dead-letter.

        * handler ناموجود ⇒ skip (نه publish) تا بعداً قابل پردازش باشد.
        * خطای handler ⇒ attempts++ و پس از max_attempts → dead-letter.
        """
        stats = {"published": 0, "failed": 0, "skipped": 0, "dead_lettered": 0}
        for event in self.pending(limit):
            handler = handlers.get(event["event_type"])
            if handler is None:
                stats["skipped"] += 1
                continue
            attempts = self.repo.attempts_for(event["event_id"])
            if attempts >= max_attempts:
                self.repo.mark_dead_letter(
                    event["event_id"], utcnow(), reason=f"max_attempts={max_attempts}",
                )
                stats["dead_lettered"] += 1
                continue
            try:
                handler(event)
            except FxarsError as exc:
                logger.warning(
                    "outbox handler failed",
                    extra={"data": {"event": event["event_id"], "error": exc.code, "attempt": attempts + 1}},
                )
                self.repo.bump_attempt(event["event_id"], last_error=str(exc))
                stats["failed"] += 1
                continue
            except Exception as exc:
                logger.exception(
                    "outbox handler crashed",
                    extra={"data": {"event": event["event_id"]}},
                )
                self.repo.bump_attempt(event["event_id"], last_error=type(exc).__name__)
                stats["failed"] += 1
                continue
            self.repo.mark_published(event["event_id"], utcnow())
            stats["published"] += 1
        return stats'''
    if old not in ob:
        print('[FAIL outbox.py] old publish_pending not found')
        sys.exit(1)
    ob = ob.replace(old, new)
    ob_p.write_text(ob, encoding='utf-8')
    print('[PATCH outbox.py] retry + dead-letter added')

print('[DONE 05a]')