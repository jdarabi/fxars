import sys
from pathlib import Path

p = Path("C:/FX/fxars/api/server.py")
text = p.read_text(encoding="utf-8")

if "FIX-08-OUTBOX-API" in text:
    print("[SKIP] server.py already patched")
else:
    # 1) ثبت route
    anchor_routes = '        add("GET", r"^/api/v1/killswitch$", self._killswitch_get, Permission.SCENARIO_READ)\n'
    if anchor_routes not in text:
        print("[FAIL] killswitch route anchor not found")
        sys.exit(1)
    new_routes = anchor_routes + (
        '        add("GET", r"^/api/v1/outbox/stats$", self._outbox_stats, Permission.AUDIT_READ)\n'
        '        add("POST", r"^/api/v1/outbox/publish$", self._outbox_publish, Permission.KILLSWITCH_TOGGLE)\n'
    )
    text = text.replace(anchor_routes, new_routes)

    # 2) افزودن handlerها
    anchor_handler = "    def _killswitch_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:\n"
    if anchor_handler not in text:
        print("[FAIL] killswitch handler anchor not found")
        sys.exit(1)
    new_handlers = '''    def _outbox_stats(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        """FIX-08-OUTBOX-API: آمار Outbox و مصرف."""
        repo = self.platform.outbox_repo
        pending = repo.pending(limit=10000)
        dead = repo.dead_letters(limit=10000)
        total_row = self.platform.db.scalar("SELECT COUNT(*) FROM outbox") or 0
        published_row = self.platform.db.scalar(
            "SELECT COUNT(*) FROM outbox WHERE published_at IS NOT NULL") or 0
        return self._json(200, {
            "pending_count": len(pending),
            "dead_letter_count": len(dead),
            "total": int(total_row),
            "published_count": int(published_row),
            "consumer": self.platform.outbox_stats.snapshot(),
        })

    def _outbox_publish(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        """FIX-08-OUTBOX-API: پردازش pending events توسط consumerها."""
        body = request.json()
        limit = int(body.get("limit", 100))
        limit = max(1, min(1000, limit))
        stats = self.platform.outbox.publish_pending(
            self.platform.outbox_handlers, limit=limit,
        )
        return self._json(200, {
            "stats": stats,
            "consumer": self.platform.outbox_stats.snapshot(),
        })

    def _killswitch_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
'''
    text = text.replace(anchor_handler, new_handlers)

    text = text.rstrip() + "\n\n# FIX-08-OUTBOX-API\n"
    p.write_text(text, encoding="utf-8")
    print("[PATCH] server.py: outbox endpoints added")
