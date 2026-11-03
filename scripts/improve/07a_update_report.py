from pathlib import Path
from datetime import date

p = Path('C:/FX/docs/IMPLEMENTATION_REPORT.md')
text = p.read_text(encoding='utf-8')

today = date.today().isoformat()
version = "1.4.11"

# 1) نسخه
if 'نسخه پیاده‌سازی' in text:
    import re
    text = re.sub(r'\*\*نسخه پیاده‌سازی:\*\*\s*`[^`]+`', f'**نسخه پیاده‌سازی:** `{version}`', text)

# 2) اضافه کردن بخش "پس از بازبینی P0/P1" در انتها
section = f"""

## بازبینی P0/P1 — {today}

در این چرخه بازبینی، ۶ مشکل بحرانی (P0) و ۳ مشکل مهم (P1) کشف و برطرف شد.

### P0 — امنیت و صحت داده

| شناسه | مشکل | راه‌حل |
|---|---|---|
| FIX-08 | Rate Limit با پیشوند توکن دور زده می‌شد | Bucket بر اساس IP قبل از auth + user_id بعد از auth |
| FIX-03 | Demo TOTP و `secret_key` پیش‌فرض ناامن | نیازمند `FXARS_ENABLE_DEMO=1` + fail-fast در prod برای کلید ضعیف |
| FIX-04a | کندل بسته با `available_at < close_time` به‌عنوان SUSPECT وارد تحلیل می‌شد (Look-ahead) | → INVALID |
| FIX-04b | کندل‌های SUSPECT و DQ FAIL وارد تحلیل/بک‌تست می‌شدند | فقط VALID + DQ FAIL → NO_TRADE |
| FIX-09a | Outbox رویدادها را با handler ناموجود گم می‌کرد | skip + retry + dead-letter (attempts، last_error، dead_letter_at) |
| FIX-09b | Idempotency غیراتمیک (Crash → Side-effect تکراری) | state=pending/completed/failed + begin/complete/fail |

### P1 — اعتبار پژوهش

| شناسه | مشکل | راه‌حل |
|---|---|---|
| FIX-06a | Swap بر اساس `bars/24` (فقط H1) | `bars × timeframe_minutes / 1440` |
| FIX-06b | Gap در Stop Loss رعایت نمی‌شد | Gap-aware fill در جهت بدتر |
| FIX-06c | Fallback `baseline` بی‌صدا بود | `fallback_count` و `fallback_errors` در stats |

### یافته‌های جانبی

- `AnalysisService` به `quality_runs` دسترسی نداشت اما DQ gate آن را می‌خواند → `AttributeError` بی‌صدا → همه تحلیل‌ها `NO_TRADE/DATA_QUALITY_FAIL` می‌دادند. تزریق `quality_runs` در `__init__` و `Platform` اضافه شد.
- `DataQualityRepository.list()` پارامتر `timeframe` ندارد. فراخوانی اصلاح شد: `list(instrument_id=..., limit=10)` + فیلتر در پایتون.
- `_with_idempotency` پیش‌فرض قبلاً "داخل تراکنش دامنه" ادعا می‌کرد، ولی نبود. حالا با state machine اتمیک است.
- دو تست قدیمی (`test_pending_count_decreases`، `test_analysis_and_idempotent_replay`) با رفتار جدید هم‌راست شدند.

### قواعد جدید

- **اولویت semantics:** `NO_DATA` < `INSUFFICIENT_DATA` < `DATA_STALE` < `DATA_QUALITY_FAIL`.
- **DQ Gate:** فقط `verdict=FAIL` صریح مانع است؛ خطای دسترسی → log + اجازه عبور.
- **Idempotency:** `failed` → retry مجاز با هر body؛ `completed/pending` با hash متفاوت → 409.
- **Outbox:** handler ناموجود → skip (نه publish).

### تست‌ها

پیش از بازبینی: 363 (2 skipped)
پس از بازبینی: 370+ (3 skipped)
- `tests/test_fixes.py` (اصلاحات P0/P1 اولیه)
- `tests/test_rate_limit_fix.py` (FIX-08)
- `tests/test_p0_p1_fixes.py` (FIX-03/04/09)
- `tests/test_backtest_fixes.py` (FIX-06)

### محدودیت‌های باقی‌مانده

- Backtest Parity کامل (استفاده از StructureResult واقعی + TriggerEvaluator در بک‌تست) در MVP-1 خارج از دامنه است. fallback در `stats` شفاف شده اما engine همچنان baseline را برای مسیر جایگزین اجرا می‌کند.
- هیچ handler واقعی برای Outbox ثبت نشده است؛ رویدادها در pending می‌مانند. این در MVP-2 با افزودن consumerها حل می‌شود.
- Rate Limit در حافظه فرآیند است؛ در استقرار چندنمونه‌ای باید به Redis/DB منتقل شود.
"""

if '## بازبینی P0/P1' not in text:
    text = text.rstrip() + section

p.write_text(text, encoding='utf-8')
print('[PATCH] IMPLEMENTATION_REPORT.md updated')