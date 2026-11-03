from pathlib import Path

p = Path('C:/FX/docs/LIMITATIONS.md')
text = p.read_text(encoding='utf-8')

addition = """

## پس از بازبینی P0/P1

- **Outbox consumer:** هیچ handler ثبت نشده است؛ رویدادها در pending می‌مانند. مصرف‌کننده‌ها در MVP-2 افزوده می‌شوند.
- **Rate Limit in-memory:** در استقرار چندنمونه‌ای باید به Redis/DB منتقل شود.
- **Backtest full parity:** Engine همچنان از StructureResult حداقلی استفاده می‌کند. `fallback_count` در stats شفاف است.
- **Idempotency cleanup:** ردیف‌های قدیمی `idempotency_keys` پاک نمی‌شوند. task نگهداری لازم است.
- **Dead-letter inspection:** endpoint/CLI برای مشاهده `dead_letters` در MVP-2 اضافه می‌شود (فعلاً فقط از طریق DB).
"""

if 'پس از بازبینی P0/P1' not in text:
    text = text.rstrip() + addition
    p.write_text(text, encoding='utf-8')
    print('[PATCH] LIMITATIONS.md updated')
else:
    print('[SKIP] LIMITATIONS.md already updated')