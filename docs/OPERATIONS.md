# راهنمای عملیات، پشتیبان‌گیری و بازیابی

## ۱. نصب

```powershell
# ویندوز: دوبار کلیک روی FXARS.bat یا
.\FXARS.bat                     # منوی فارسی
.\FXARS.bat serve --port 8080   # اجرای مستقیم API (پورت ثابت)
```

منوی `FXARS.bat` این گزینه‌ها را دارد: اجرای داشبورد (پورت خودکار)، تحلیل، ریسک، بک‌تست، ممیزی، آزمون‌ها، داده دمو، **توقف داشبورد** و **خروج**. سرور در رشته پس‌زمینه اجرا می‌شود؛ بنابراین منو قفل نمی‌شود و با گزینه ۰ سرور متوقف و پنجره بسته می‌شود. متغیرهای اختیاری:

| متغیر | اثر |
|---|---|
| `FXARS_PORT` | پورت ثابت داشبورد (پیش‌فرض: پورت آزاد خودکار) |
| `FXARS_NO_BROWSER=1` | باز نکردن خودکار مرورگر |
| `FXARS_NO_PAUSE=1` | توقف نکردن پنجره در خطا (برای اسکریپت) |

خط فرمان مستقیم:

```powershell
python -m fxars init --db data/fxars.db
python -m fxars seed-demo --data-dir data
python -m fxars serve --host 127.0.0.1 --port 8080
```

برای نصب به‌عنوان بسته (اختیاری): `pip install -e .` سپس `fxars --help`.

## ۲. پیکربندی

- پیش‌فرض: `fxars/config/settings.py`
- بازنویسی: `config/settings.json` (نمونه `config/settings.example.json`)
- محیط: `FXARS_PHASE`, `FXARS_DB_PATH`, `FXARS_SECRET_KEY`, `FXARS_API_HOST`, `FXARS_API_PORT`, `FXARS_SEED`
- تغییر پارامترهای ریسک/تحلیل = تغییر `config_hash` و نیازمند بازآزمون رگرسیون.

**کلید امنیتی:** `secret_key` پیش‌فرض فقط توسعه است؛ در تولید از KMS/Secret Manager و مقدار ۳۲+ بایت تصادفی استفاده کنید.

## ۳. پشتیبان‌گیری

```powershell
# روش سازگار با WAL: VACUUM INTO
python -c "import sqlite3; c=sqlite3.connect('data/fxars.db'); c.execute(\"VACUUM INTO 'backup/fxars-2026-11-01.db'\"); c.close()"
```

- پشتیبان را رمزنگاری و خارج از میزبان نگه دارید (۳-۲-۱).
- داده خام (`raw_payloads`) و Audit باید در پشتیبان حفظ شوند.
- نسخه پشتیبان تا آزمون Restore قابل اتکا نیست.

## ۴. بازیابی

1. سرویس را متوقف کنید.
2. فایل پشتیبان را در مسیر `FXARS_DB_PATH` قرار دهید (فایل‌های `-wal`/`-shm` قدیمی را حذف کنید).
3. `python -m fxars audit verify` — زنجیره باید معتبر باشد.
4. `python -m fxars init` (idempotent) و بررسی `health`.
5. حساب‌ها/سفارش‌ها را با بروکر تطبیق دهید (در فاز اجرا).
6. RPO/RTO مصوب را ثبت کنید؛ هدف پیشنهادی MVP: RPO ≤ ۱۵ دقیقه، RTO ≤ ۱ ساعت پس از تصویب.

## ۵. پایش

| شاخص | مسیر/منبع |
|---|---|
| سلامت | `GET /api/v1/health` |
| تازگی داده | `GET /api/v1/data-quality/runs` |
| خطاها | لاگ JSON با `correlation_id` |
| تصمیم‌ها | `GET /api/v1/risk/decisions` |
| ممیزی | `GET /api/v1/audit-events` + `audit verify` |
| Kill Switch | `GET /api/v1/killswitch` |

هشدارها: داده STALE، شکست Ingestion، خطای محاسبه ریسک، فعال‌شدن Kill Switch، اختلاف تطبیق.

## ۶. Runbook رخداد

**داده کهنه/قطع فید**
1. `data-quality/runs` را بررسی کنید (verdict/STALE).
2. تحلیل متوقف و NO TRADE می‌شود (Fail-Safe)؛ دخالت دستی لازم نیست.
3. منبع را بررسی و پس از بازگشت، DQ را تأیید کنید.

**خطای محاسباتی/ریسک**
1. `correlation_id` را از پاسخ/لاگ بردارید.
2. Run و RiskDecision را بازیابی کنید؛ `inputs_hash` را بررسی کنید.
3. در صورت ابهام Kill Switch فعال کنید.

**فعال‌سازی Kill Switch**
```powershell
python -m fxars killswitch on --reason "ناهنجاری داده" --actor operator
python -m fxars killswitch status
python -m fxars killswitch off --reason "رفع مشکل" --actor operator
```
هر تغییر در Audit ثبت می‌شود.

**اختلاف تطبیق سفارش (فاز اجرا)**
1. سفارش‌های `UNKNOWN` را به `RECONCILIATION_REQUIRED` ببرید.
2. با `client_order_id` در بروکر جست‌وجو کنید؛ ارسال مجدد کورکورانه ممنوع.
3. نتیجه را ثبت و Audit کنید.

## ۷. ارتقا

1. پشتیبان + آزمون Restore.
2. `python -m unittest discover -s tests` و `python -m fxars ac`.
3. مهاجرت Schema نسخه‌دار (`schema_migrations`)؛ rollback داده جدا از rollback schema.
4. انتشار با نسخه جدید `CODE_VERSION` و ثبت تغییر.

## ۸. چرخش کلید/رمز

- TOTP کاربران: ایجاد Secret جدید و جایگزینی امن.
- رمز: `IdentityService.set_password` (نشست‌ها باید باطل شوند).
- `secret_key`: پس از چرخش، اسرار TOTP موجود باید بازرمزنگاری شوند (خارج از دامنه MVP-1؛ رویه مستند شود).
