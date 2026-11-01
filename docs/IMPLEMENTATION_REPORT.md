# گزارش پیاده‌سازی — FX-ARS MVP-1

سند مبنا: `FX-ARS-SRS-ARCH-002` (نسخه ۲.۱) — نسخه پیاده‌سازی: `1.3.0` — قواعد: `rules_v1.3.0`

## ۱. خلاصه

پروژه به‌صورت یک **Modular Monolith** کامل با پایتون و تنها کتابخانه استاندارد پیاده‌سازی شد. فاز MVP-1 (تحلیل و پشتیبانی تصمیم، فقط‌خواندنی و بدون ارسال سفارش) به‌طور کامل اجراشدنی و آزمون‌شده است. اسکلت فازهای MVP-2+ (Order State Machine، PaperBroker، Phase Guard) نیز با قراردادهای روشن آماده شده اما در فاز فعلی مسدود است.

| شاخص | مقدار |
|---|---|
| فایل‌های پایتون | ۸۵ |
| خطوط کد پایتون | ~۱۰٬۵۰۰ |
| فایل‌های آزمون | ۱۲ |
| خطوط آزمون | ~۱٬۵۰۰ |
| آزمون‌ها | **۱۵۹ — همه موفق** |
| معیارهای پذیرش | **AC-01..AC-12 — همه موفق** |
| وابستگی خارجی | هیچ (Python 3.11+) |
| مستندات | ۱۲ سند فارسی |

## ۲. تحویل‌دادنی‌ها

### هسته و دامنه
- مدل‌های تغییرناپذیر با `Decimal` و UTC؛ قرارداد Candle/Evidence/Scenario/RiskDecision/OrderIntent
- پیکربندی نسخه‌دار با `config_hash`؛ نسخه‌بندی کد/قواعد/سیاست ریسک
- تقویم فارکس ۲۴/۵ با DST، تعطیلات و کندل‌های مورد انتظار

### داده و کیفیت
- اعتبارسنجی OHLC/زمان/اسپرد/دقت، قرنطینه داده INVALID (AC-01)
- گزارش کیفیت: شکاف، تکراری، کهنگی، واگرایی منابع، پرش قیمت
- نسخه‌بندی اصلاحات (`candle_revision_log`) و Raw فقط‌افزودنی
- فید CSV و مولد داده قطعی دمو (۴۶۵۸ کندل H1 + DXY + ۵۷ رویداد)

### تحلیل و تصمیم
- ۱۲ ماژول نسخه‌دار: Swing/BOS/CHoCH/FVG/Order Block/Sweep/Displacement، روند، مومنتوم، نوسان، حجم، سطوح، بنیادی، بین‌بازاری
- قرارداد Evidence با `observed_at`/`available_at`/ابطال/انقضا/پارامتر‌هش
- تجمیع خانواده‌ای با سقف سهم، کنترل تعارض/پوشش/پایداری و NO TRADE صریح
- ماشین حالت سناریو با Transition ثبت‌شده و ارزیاب Trigger/Invalidation/Expiry

### ریسک
- اندازه موقعیت Decimal با نرخ تبدیل ارز و کمیسیون
- ۲۰ کنترل مستقل، RiskDecision با `inputs_hash` و `valid_until`
- Kill Switch سراسری با Audit و Outbox
- Phase Guard: در MVP-1 هر OrderIntent با `PHASE_VIOLATION` رد می‌شود (AC-05)

### پژوهش
- بک‌تست رویدادمحور با مدل اسپرد/کمیسیون/سوآپ/لغزش، Stop-first و ورود در کندل بعد
- تفکیک هزینه‌ها (AC-07)، OOS سه‌بخشی + Embargo (AC-08)، Walk-forward، PBO، DSR، Monte Carlo
- گزارش Markdown/HTML با نمودار SVG

### API، UI، امنیت، ممیزی
- API نسخه‌دار `/api/v1` با RBAC، Idempotency، Rate Limit، خطای ساختاریافته و OpenAPI
- داشبورد فارسی RTL: تحلیل، سناریو، ریسک، بک‌تست، عملیات
- PBKDF2 + TOTP + نشست‌های قابل ابطال
- Audit زنجیره‌هش فقط‌افزودنی + Transactional Outbox
- بازتولیدپذیری: `run_id`/`result_hash` مشتق از Snapshot، Config و نسخه‌ها (AC-02)

## ۳. نتیجه اجرای دمو (Seed=7، EURUSD/H1)

| مورد | مقدار |
|---|---|
| کندل‌ها | ۴۶۵۸ (۲۰۲۶-۰۲-۰۱ تا ۲۰۲۶-۱۰-۳۰) |
| کیفیت داده | PASS (۰ قرنطینه، ۰ شکاف) |
| AnalysisRun | `ar_736251378bc000988dc6265b` — COMPLETED |
| تصمیم | SHORT، امتیاز ‎−0.386، پوشش ۷۱٪، پایداری ۱۰۰٪ |
| سناریو | `sc_e5fc0440e0eb17291a91d216` — WATCH |
| RiskDecision | `rd_8c5cc47c3b196b5b9fd96004` — APPROVED، حجم ۰٫۰۸ لات، ریسک ۲۵ USD |
| بک‌تست | `bt_9358fec25629a65c1d44b3e8` |
| معاملات | ۳۹۸ (Win 52.3٪، PF 1.14، Net +225.50، MDD 1.55٪) |
| Sharpe / Sortino / Calmar | 1.18 / 1.68 / 2.00 |
| DSR (trials=1) | 0.843 |
| هزینه‌ها | اسپرد ۱۰۷٫۴۱ + کمیسیون ۷۰٫۷۷ + لغزش ۶۰٫۶۶ + سوآپ ‎−۸٫۳۸ = ۲۳۰٫۴۶ |

گزارش کامل: `reports/backtest_bt_9358fec25629a65c1d44b3e8.html`

> این اعداد خروجی یک baseline روی داده شبیه‌سازی‌شده است و مبنای تصمیم سرمایه‌گذاری نیست.

## ۴. آزمون و پذیرش

```
python -m unittest discover -s tests      # 156 tests — OK
python -m unittest tests.test_acceptance   # AC-01..AC-12 — OK
```

نگاشت کامل ACها: [ACCEPTANCE.md](ACCEPTANCE.md)

## ۵. اجرای سریع

```powershell
python -m fxars init
python -m fxars seed-demo
python -m fxars analyze --instrument EURUSD --timeframe H1
python -m fxars risk --scenario <id>
python -m fxars backtest --instrument EURUSD --timeframe H1 --report
python -m fxars serve --port 8080
```

## ۶. شکاف‌های باقی‌مانده (شفاف)

1. فید داده واقعی و آداپتر بروکر متصل نشده؛ نقاط اتصال طراحی شده‌اند.
2. SQLite برای MVP-1؛ مهاجرت PostgreSQL و Partitioning در فاز تولید.
3. `SecretBox` جایگزین‌پذیر با KMS است؛ Rate Limit درون‌فرآیندی است.
4. ML/Deep Learning خارج از دامنه MVP-1.
5. چندمستاجری و صورت‌حساب تجاری (MVP-4) پیاده نشده.
6. تصویب پارامترهای ریسک/OOS و حقوق داده نیازمند مالک محصول و مشاور حقوقی است.

جزئیات: [LIMITATIONS.md](LIMITATIONS.md) و [DECISIONS.md](DECISIONS.md)
