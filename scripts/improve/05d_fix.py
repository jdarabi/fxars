from pathlib import Path

p = Path('C:/FX/fxars/storage/repositories.py')
text = p.read_text(encoding='utf-8')

old = '''        row = self.db.query_one(
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
            # state == "failed" → fall through → اجرای دوباره'''

new = '''        row = self.db.query_one(
            "SELECT state, request_hash, status, response FROM idempotency_keys WHERE key=? AND user_id=?",
            (key, user_id),
        )
        if row is not None:
            state = row["state"] or "completed"
            # FIX-09-IDEMPOTENCY-ATOMIC: state='failed' → همیشه اجازه retry (حتی با hash متفاوت)
            if state == "failed":
                # fall through → اجرای دوباره با hash جدید
                pass
            elif row["request_hash"] != request_hash:
                # completed/pending با hash متفاوت → conflict
                return ("conflict", None)
            elif state == "completed":
                return ("replay", {"status": int(row["status"]), "response": _load(row["response"])})
            elif state == "pending":
                return ("in_progress", None)'''

if old not in text:
    print('[FAIL] begin() block not found')
    raise SystemExit(1)

text = text.replace(old, new)
p.write_text(text, encoding='utf-8')
print('[PATCH] begin() now allows retry after fail with new hash')
print('[DONE 05d]')