from pathlib import Path
import sys

p = Path("C:/FX/fxars/platform.py")
text = p.read_text(encoding="utf-8")

if "FIX-08-OUTBOX-CONSUMER" in text:
    print("[SKIP] platform.py already patched")
else:
    anchor = "    # ------------------------------------------------------------------ راه‌اندازی\n"
    if anchor not in text:
        print("[FAIL] bootstrap anchor not found")
        sys.exit(1)

    addition = """        # FIX-08-OUTBOX-CONSUMER: ثبت consumerهای پیش‌فرض
        from fxars.audit.handlers import ConsumerStats, default_handlers
        self.outbox_stats = ConsumerStats()
        self.outbox_handlers = default_handlers(stats=self.outbox_stats)

    # ------------------------------------------------------------------ راه‌اندازی
"""
    text = text.replace(anchor, addition)
    p.write_text(text, encoding="utf-8")
    print("[PATCH] platform.py: outbox handlers registered")