from pathlib import Path
import sys

# ===========================================================================
# 1) schema.sql: افزودن ستون state
# ===========================================================================
schema_p = Path('C:/FX/fxars/storage/schema.sql')
schema = schema_p.read_text(encoding='utf-8')

if 'state TEXT NOT NULL DEFAULT' in schema:
    print('[SKIP schema] state already present')
else:
    old = '''CREATE TABLE IF NOT EXISTS idempotency_keys (
    key          TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    route        TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status       INTEGER NOT NULL,
    response     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (key, user_id)
);'''
    new = '''CREATE TABLE IF NOT EXISTS idempotency_keys (
    key          TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    route        TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status       INTEGER NOT NULL,
    response     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    state        TEXT NOT NULL DEFAULT 'completed',
    PRIMARY KEY (key, user_id)
);'''
    if old not in schema:
        print('[FAIL schema] table block not found')
        sys.exit(1)
    schema = schema.replace(old, new)
    schema_p.write_text(schema, encoding='utf-8')
    print('[PATCH schema] idempotency_keys.state added')

# ===========================================================================
# 2) db.py
# ===========================================================================
db_p = Path('C:/FX/fxars/storage/db.py')
db = db_p.read_text(encoding='utf-8')

if 'idempotency_keys", "state"' in db:
    print('[SKIP db.py] already present')
else:
    old = '''            self._ensure_column("outbox", "dead_letter_at", "TEXT")
'''
    new = '''            self._ensure_column("outbox", "dead_letter_at", "TEXT")
            # FIX-09-IDEMPOTENCY-ATOMIC
            self._ensure_column("idempotency_keys", "state", "TEXT NOT NULL DEFAULT 'completed'")
'''
    if old not in db:
        print('[FAIL db.py] anchor not found')
        sys.exit(1)
    db = db.replace(old, new)
    db_p.write_text(db, encoding='utf-8')
    print('[PATCH db.py] state ensure added')

# ===========================================================================
# 3) repositories.py
# ===========================================================================
repo_p = Path('C:/FX/fxars/storage/repositories.py')
repo = repo_p.read_text(encoding='utf-8')

if 'def begin(self, key' in repo:
    print('[SKIP repositories] begin() already present')
else:
    old = '''    def put(self, key: str, user_id: str, route: str, request_hash: str, status: int, response: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO idempotency_keys (key, user_id, route, request_hash, status, response, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, user_id, route, request_hash, status, _dump(response), format_ts(utcnow())),
        )'''
    new = '''    def put(self, key: str, user_id: str, route: str, request_hash: str, status: int, response: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO idempotency_keys (key, user_id, route, request_hash, status, response, created_at, state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'completed')",
            (key, user_id, route, request_hash, status, _dump(response), format_ts(utcnow())),
        )

    def begin(self, key: str, user_id: str, route: str, request_hash: str) -> tuple[str, dict[str, Any] | None]:
        """FIX-09-IDEMPOTENCY-ATOMIC: ثبت pending اتمیک قبل از Action.

        ("replay", response)  | ("conflict", None) | ("in_progress", None) | ("proceed", None)
        """
        row = self.db.query_one(
            "SELECT state, request_hash, status, response FROM idempotency_keys WHERE key=? AND user_id=?",
            (key, user_id),
        )
        if row is not None:
            if row["request_hash"] != request_hash:
                return ("conflict", None)
            state = row["state"] or "completed"
            if state == "completed":
                return ("replay", {"status": int(row["status"]), "response": _load(row["response"])})
            if state == "pending":
                return ("in_progress", None)
            # state == "failed" → fall through → اجرای دوباره
        self.db.execute(
            "INSERT OR REPLACE INTO idempotency_keys "
            "(key, user_id, route, request_hash, status, response, created_at, state) "
            "VALUES (?, ?, ?, ?, 0, '{}', ?, 'pending')",
            (key, user_id, route, request_hash, format_ts(utcnow())),
        )
        return ("proceed", None)

    def complete(self, key: str, user_id: str, status: int, response: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE idempotency_keys SET status=?, response=?, state='completed' "
            "WHERE key=? AND user_id=?",
            (status, _dump(response), key, user_id),
        )

    def fail(self, key: str, user_id: str) -> None:
        self.db.execute(
            "UPDATE idempotency_keys SET state='failed' WHERE key=? AND user_id=?",
            (key, user_id),
        )'''
    if old not in repo:
        print('[FAIL repositories] put() anchor not found')
        sys.exit(1)
    repo = repo.replace(old, new)
    repo_p.write_text(repo, encoding='utf-8')
    print('[PATCH repositories] begin/complete/fail added')

# ===========================================================================
# 4) server.py
# ===========================================================================
srv_p = Path('C:/FX/fxars/api/server.py')
srv = srv_p.read_text(encoding='utf-8')

if 'idempotency.begin' in srv:
    print('[SKIP server] begin() already used')
else:
    old = '''        existing = self.platform.idempotency.get(key, user.user_id)
        if existing is not None:
            if existing["request_hash"] != request_hash:
                from fxars.core.errors import IdempotencyConflictError

                raise IdempotencyConflictError(details={"key": key})
            return self._json(existing["status"], existing["response"])
        response = action()
        payload = json.loads(response.body.decode("utf-8")) if response.body else {}
        self.platform.idempotency.put(key, user.user_id, request.path, request_hash, response.status, payload)
        return response'''
    new = '''        # FIX-09-IDEMPOTENCY-ATOMIC
        outcome, existing = self.platform.idempotency.begin(
            key, user.user_id, request.path, request_hash,
        )
        if outcome == "replay" and existing is not None:
            return self._json(existing["status"], existing["response"])
        if outcome == "conflict":
            from fxars.core.errors import IdempotencyConflictError
            raise IdempotencyConflictError(details={"key": key})
        if outcome == "in_progress":
            from fxars.core.errors import ConflictError
            raise ConflictError(
                "درخواست با همین Idempotency-Key در حال پردازش است؛ دوباره تلاش کنید.",
                details={"key": key},
            )

        try:
            response = action()
        except Exception:
            self.platform.idempotency.fail(key, user.user_id)
            raise

        payload = json.loads(response.body.decode("utf-8")) if response.body else {}
        self.platform.idempotency.complete(key, user.user_id, response.status, payload)
        return response'''
    if old not in srv:
        print('[FAIL server] _with_idempotency block anchor not found')
        sys.exit(1)
    srv = srv.replace(old, new)
    srv_p.write_text(srv, encoding='utf-8')
    print('[PATCH server] _with_idempotency atomic')

print('[DONE 05b]')