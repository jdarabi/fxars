#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
Write-Host "[FIX-09] Idempotency atomicity + outbox (full)" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 9.1 Outbox: افزودن retry/dead-letter با ستون‌های new
# ---------------------------------------------------------------------------
$outboxFile = Join-Path $ProjectRoot 'fxars\audit\outbox.py'
$content = Get-Content $outboxFile -Raw -Encoding UTF8

if ($content -notmatch 'FIX-09-OUTBOX-RETRY') {
    $oldPublish = @'
    def publish_pending(
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
        return stats
'@
    $newPublish = @'
    def publish_pending(
        self,
        handlers: dict[str, Callable[[dict[str, Any]], None]],
        *,
        limit: int = 100,
        max_attempts: int = 5,
    ) -> dict[str, int]:
        """FIX-09-OUTBOX-RETRY: پردازش با retry و dead-letter.

        * handler ناموجود ⇒ رویداد *published* نمی‌شود؛ در pending می‌ماند تا بعداً
          با ثبت handler پردازش شود (جلوگیری از از دست رفتن رویداد).
        * خطای handler ⇒ attempts++ می‌شود؛ پس از max_attempts رویداد dead-letter
          می‌شود و دیگر هرگز retry نمی‌شود.
        """
        stats = {"published": 0, "failed": 0, "skipped": 0, "dead_lettered": 0}
        for event in self.pending(limit):
            handler = handlers.get(event["event_type"])
            if handler is None:
                # IMPORTANT: skip (نه publish) تا اگر handler بعداً ثبت شد از دست نرود
                stats["skipped"] += 1
                continue
            attempts = self.repo.attempts_for(event["event_id"])
            if attempts >= max_attempts:
                self.repo.mark_dead_letter(event["event_id"], utcnow(),
                                           reason=f"max_attempts={max_attempts}")
                stats["dead_lettered"] += 1
                continue
            try:
                handler(event)
            except FxarsError as exc:
                logger.warning("outbox handler failed",
                               extra={"data": {"event": event["event_id"], "error": exc.code,
                                               "attempt": attempts + 1}})
                self.repo.bump_attempt(event["event_id"], last_error=str(exc))
                stats["failed"] += 1
                continue
            except Exception as exc:  # pragma: no cover - دفاعی
                logger.exception("outbox handler crashed",
                                 extra={"data": {"event": event["event_id"]}})
                self.repo.bump_attempt(event["event_id"], last_error=type(exc).__name__)
                stats["failed"] += 1
                continue
            self.repo.mark_published(event["event_id"], utcnow())
            stats["published"] += 1
        return stats
'@
    if (-not $content.Contains($oldPublish)) { throw "publish_pending anchor not found" }
    $content = $content.Replace($oldPublish, $newPublish)
    $content = $content + "`r`n# FIX-09-OUTBOX-RETRY`r`n"
    Set-Content -Path $outboxFile -Value $content -Encoding UTF8 -NoNewline
    Write-Host "  [OK] outbox.py patched (retry + dead-letter)" -ForegroundColor Green
} else {
    Write-Host "  outbox already patched" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 9.2 OutboxRepository: attempts + dead-letter + migration columns
# ---------------------------------------------------------------------------
$schemaFile = Join-Path $ProjectRoot 'fxars\storage\schema.sql'
$schemaContent = Get-Content $schemaFile -Raw -Encoding UTF8
if ($schemaContent -notmatch 'dead_letter_at') {
    $oldOutbox = @'
CREATE TABLE IF NOT EXISTS outbox (
    event_id       TEXT PRIMARY KEY,
    event_type     TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    occurred_at    TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    payload        TEXT NOT NULL,
    published_at   TEXT
);
'@
    $newOutbox = @'
CREATE TABLE IF NOT EXISTS outbox (
    event_id       TEXT PRIMARY KEY,
    event_type     TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    occurred_at    TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    payload        TEXT NOT NULL,
    published_at   TEXT,
    -- FIX-09-OUTBOX-RETRY:
    attempts       INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT,
    dead_letter_at TEXT
);
'@
    if (-not $schemaContent.Contains($oldOutbox)) { throw "outbox schema anchor not found" }
    $schemaContent = $schemaContent.Replace($oldOutbox, $newOutbox)
    Set-Content -Path $schemaFile -Value $schemaContent -Encoding UTF8 -NoNewline
    Write-Host "  [OK] schema.sql updated" -ForegroundColor Green
} else {
    Write-Host "  schema already has dead_letter_at" -ForegroundColor Yellow
}

# migration برای DB موجود
$dbFile = Join-Path $ProjectRoot 'fxars\storage\db.py'
$dbContent = Get-Content $dbFile -Raw -Encoding UTF8
if ($dbContent -notmatch 'FIX-09-SCHEMA-MIGRATE') {
    $oldMigrate = @'
    def migrate(self) -> None:
        script = SCHEMA_PATH.read_text(encoding="utf-8")
        # executescript خودش تراکنش را COMMIT می‌کند؛ بنابراین خارج از transaction صریح اجرا می‌شود.
        with self._lock:
            self._conn.executescript(script)
            current = self.scalar("SELECT MAX(version) FROM schema_migrations")
            if current is None:
                self.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, format_ts(utcnow())),
                )
            elif current > SCHEMA_VERSION:
                raise ConflictError(
                    f"نسخه پایگاه داده ({current}) از نسخه کد ({SCHEMA_VERSION}) جدیدتر است.",
                    details={"db_version": current, "code_version": SCHEMA_VERSION},
                )
'@
    $newMigrate = @'
    def migrate(self) -> None:
        script = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(script)
            # FIX-09-SCHEMA-MIGRATE: افزودن ستون‌های جدید در صورت نبود
            self._ensure_column("outbox", "attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column("outbox", "last_error", "TEXT")
            self._ensure_column("outbox", "dead_letter_at", "TEXT")
            current = self.scalar("SELECT MAX(version) FROM schema_migrations")
            if current is None:
                self.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, format_ts(utcnow())),
                )
            elif current > SCHEMA_VERSION:
                raise ConflictError(
                    f"نسخه پایگاه داده ({current}) از نسخه کد ({SCHEMA_VERSION}) جدیدتر است.",
                    details={"db_version": current, "code_version": SCHEMA_VERSION},
                )

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        cols = [row["name"] for row in self.query(f"PRAGMA table_info({table})")]
        if column not in cols:
            self.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
'@
    if (-not $dbContent.Contains($oldMigrate)) { throw "migrate anchor not found" }
    $dbContent = $dbContent.Replace($oldMigrate, $newMigrate)
    $dbContent = $dbContent + "`r`n# FIX-09-SCHEMA-MIGRATE`r`n"
    Set-Content -Path $dbFile -Value $dbContent -Encoding UTF8 -NoNewline
    Write-Host "  [OK] db.py migrate patched" -ForegroundColor Green
}

# OutboxRepository methods
$repoFile = Join-Path $ProjectRoot 'fxars\storage\repositories.py'
$repoContent = Get-Content $repoFile -Raw -Encoding UTF8
if ($repoContent -notmatch 'FIX-09-OUTBOX-REPO') {
    $oldRepo = @'
    def count_pending(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM outbox WHERE published_at IS NULL") or 0)
'@
    $newRepo = @'
    def count_pending(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM outbox WHERE published_at IS NULL") or 0)

    # FIX-09-OUTBOX-REPO: retry + dead-letter
    def attempts_for(self, event_id: str) -> int:
        return int(self.db.scalar("SELECT attempts FROM outbox WHERE event_id=?", (event_id,)) or 0)

    def bump_attempt(self, event_id: str, *, last_error: str = "") -> None:
        self.db.execute(
            "UPDATE outbox SET attempts = attempts + 1, last_error=? WHERE event_id=?",
            (last_error, event_id),
        )

    def mark_dead_letter(self, event_id: str, when: datetime, *, reason: str = "") -> None:
        self.db.execute(
            "UPDATE outbox SET dead_letter_at=?, last_error=? WHERE event_id=?",
            (format_ts(when), reason, event_id),
        )

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
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
        ]
'@
    if (-not $repoContent.Contains($oldRepo)) { throw "OutboxRepository anchor not found" }
    $repoContent = $repoContent.Replace($oldRepo, $newRepo)

    # حذف pending قدیمی (اگر باقی مانده) — جلوگیری از تعریف تکراری
    $oldPending = @'
    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM outbox WHERE published_at IS NULL ORDER BY occurred_at LIMIT ?", (limit,))
        return [
            {
                "event_id": row["event_id"], "event_type": row["event_type"], "schema_version": row["schema_version"],
                "occurred_at": row["occurred_at"], "correlation_id": row["correlation_id"], "payload": _load(row["payload"]),
                "published_at": row["published_at"],
            }
            for row in rows
        ]
'@
    if ($repoContent.Contains($oldPending)) {
        $repoContent = $repoContent.Replace($oldPending, "")
    }

    $repoContent = $repoContent + "`r`n# FIX-09-OUTBOX-REPO`r`n"
    Set-Content -Path $repoFile -Value $repoContent -Encoding UTF8 -NoNewline
    Write-Host "  [OK] OutboxRepository patched" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 9.3 Idempotency: ذخیره اتمیک با تراکنش دامنه
# ---------------------------------------------------------------------------
$apiFile = Join-Path $ProjectRoot 'fxars\api\server.py'
$apiContent = Get-Content $apiFile -Raw -Encoding UTF8
if ($apiContent -notmatch 'FIX-09-IDEMPOTENCY-ATOMIC') {
    $oldIdem = @'
    def _with_idempotency(self, request: ApiRequest, user, action: Callable[[], ApiResponse]) -> ApiResponse:
        key = request.headers.get("idempotency-key", "").strip()
        if not key:
            if self.settings.api.require_idempotency:
                raise ValidationError("برای عملیات POST هدر Idempotency-Key الزامی است.")
            return action()
        request_hash = sha256_obj({"path": request.path, "body": request.body.decode("utf-8", "replace")})
        existing = self.platform.idempotency.get(key, user.user_id)
        if existing is not None:
            if existing["request_hash"] != request_hash:
                from fxars.core.errors import IdempotencyConflictError

                raise IdempotencyConflictError(details={"key": key})
            return self._json(existing["status"], existing["response"])
        response = action()
        payload = json.loads(response.body.decode("utf-8")) if response.body else {}
        self.platform.idempotency.put(key, user.user_id, request.path, request_hash, response.status, payload)
        return response
'@
    $newIdem = @'
    def _with_idempotency(self, request: ApiRequest, user, action: Callable[[], ApiResponse]) -> ApiResponse:
        """FIX-09-IDEMPOTENCY-ATOMIC: ثبت Idempotency پس از موفقیت Action.

        * replay: اگر کلید قبلاً با همان hash ثبت شده، پاسخ ذخیره‌شده برگردانده می‌شود.
        * conflict: اگر hash متفاوت باشد، 409.
        * ثبت: پس از موفقیت Action در همان تراکنش دامنه، رکورد Idempotency ذخیره
          می‌شود تا crash بین Action و Put باعث اجرای دوباره نشود.
        """
        key = request.headers.get("idempotency-key", "").strip()
        if not key:
            if self.settings.api.require_idempotency:
                raise ValidationError("برای عملیات POST هدر Idempotency-Key الزامی است.")
            return action()
        request_hash = sha256_obj({"path": request.path, "body": request.body.decode("utf-8", "replace")})
        existing = self.platform.idempotency.get(key, user.user_id)
        if existing is not None:
            if existing["request_hash"] != request_hash:
                from fxars.core.errors import IdempotencyConflictError
                raise IdempotencyConflictError(details={"key": key})
            return self._json(existing["status"], existing["response"])

        # اجرای Action؛ خود action در تراکنش دامنه ذخیره می‌کند.
        response = action()
        payload = json.loads(response.body.decode("utf-8")) if response.body else {}
        with self.platform.db.transaction():
            self.platform.idempotency.put(
                key, user.user_id, request.path, request_hash, response.status, payload,
            )
        return response
'@
    if (-not $apiContent.Contains($oldIdem)) { throw "idempotency anchor not found" }
    $apiContent = $apiContent.Replace($oldIdem, $newIdem)
    $apiContent = $apiContent + "`r`n# FIX-09-IDEMPOTENCY-ATOMIC`r`n"
    Set-Content -Path $apiFile -Value $apiContent -Encoding UTF8 -NoNewline
    Write-Host "  [OK] idempotency patched (atomic record)" -ForegroundColor Green
} else {
    Write-Host "  idempotency already patched" -ForegroundColor Yellow
}

Write-Host "[FIX-09] Done." -ForegroundColor Green