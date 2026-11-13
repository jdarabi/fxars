# گزارش پیاده‌سازی — FX-ARS

سند مبنا: `FX-ARS-SRS-ARCH-002` (نسخه ۲.۱) + «سند تکمیلی ۱.۱» — نسخه پیاده‌سازی: `1.11.0` — قواعد: `rules_v1.3.0`

## ۱. خلاصه

پروژه به‌صورت یک **Modular Monolith** کامل با پایتون و تنها کتابخانه استاندارد پیاده‌سازی شد. فازهای ۰ تا ۷ نقشه راه سند (تحلیل، داده، تحلیل پایه، آزمایشگاه، ریسک، هوشمندی، دمو، تجاری) پیاده‌سازی و آزمون‌شده‌اند. فاز اجرای واقعی (`ASSISTED`/`AUTOMATED_LIMITED`) فقط با تأیید رسمی اپراتور فعال می‌شود؛ پیش‌فرض سامانه `READ_ONLY` است.

| شاخص | مقدار |
|---|---|
| نسخه | **1.11.0** |
| فایل‌های پایتون | 148 |
| خطوط کد پایتون | ~33,325 |
| فایل‌های آزمون | 68 |
| خطوط آزمون | ~12,315 |
| آزمون‌ها | **781 (7 skip: live Postgres بدون DSN و آزمون‌های محیطی)** |
| معیارهای پذیرش | **AC-01..AC-12 و AC-S01..AC-S14 — همه موفق (S14: بازبینی مرورگر انجام شد)** |
| وابستگی اجباری | هیچ (Python 3.11+) |
| وابستگی اختیاری | `hypothesis` (تست)، `psycopg` (Postgres) |
| مستندات | 14 سند فارسی + CHANGELOG |

## ۲. تحویل‌دادنی‌ها

### هسته و دامنه
- مدل‌های تغییرناپذیر با `Decimal` و UTC؛ قرارداد Candle/Evidence/Scenario/RiskDecision/OrderIntent/BrokerOrder/Fill
- پیکربندی نسخه‌دار با `config_hash`؛ نسخه‌بندی کد/قواعد/سیاست ریسک
- تقویم فارکس ۲۴/۵ با DST، تعطیلات و کندل‌های مورد انتظار
- **FIX-P0-2**: bitemporal invariants (Candle.available_at ≥ close_time؛ EconomicEvent.available_at ≥ event_time/published_at)

### داده و کیفیت
- اعتبارسنجی OHLC/زمان/اسپرد/دقت، قرنطینه داده INVALID (AC-01)
- گزارش کیفیت: شکاف، تکراری، کهنگی، واگرایی منابع، پرش قیمت
- نسخه‌بندی اصلاحات (`candle_revision_log`) و Raw فقط‌افزودنی
- فید CSV و مولد داده قطعی دمو (۴۶۵۸ کندل H1 + DXY + ۵۷ رویداد)

### تحلیل و تصمیم
- **۱۴ ماژول نسخه‌دار**: Swing/BOS/CHoCH/FVG/Order Block/Sweep/Displacement، روند، مومنتوم، نوسان، حجم، سطوح، بنیادی، بین‌بازاری، **Regime Detection**
- قرارداد Evidence با `observed_at`/`available_at`/ابطال/انقضا/پارامتر‌هش
- تجمیع خانواده‌ای با سقف سهم، کنترل تعارض/پوشش/پایداری و NO TRADE صریح
- ماشین حالت سناریو با Transition ثبت‌شده و ارزیاب Trigger/Invalidation/Expiry

### ریسک
- اندازه موقعیت Decimal با نرخ تبدیل ارز و کمیسیون
- ۲۱ کنترل مستقل، RiskDecision با `inputs_hash` و `valid_until`
- Kill Switch سراسری با Audit و Outbox
- Phase Guard: در `READ_ONLY` هر OrderIntent با `PHASE_VIOLATION` رد می‌شود (AC-05)

### پژوهش (P3)
- **P3-1 Triple Barrier**: `fxars/research/labeling.py` با config/ATR/labels/stats
- **P3-1-ext ML Pipeline**: ادغام Triple Barrier + Purged K-Fold
- **P3-2 Purged K-Fold**: `fxars/research/purged_cv.py` با purge و embargo
- **P3-3 Calibration**: Brier/LogLoss/ECE/MCE + Temperature Scaling + Reliability Diagram (AC-09)
- **P3-4 Regime Detection**: ۵ رژیم با اولویت LOW_VOL > TRENDING > HIGH_VOL > RANGING
- **P3-4-ext2 Regime Filter**: `BacktestConfig.allowed_regimes` (**+144% net profit** روی دمو)
- **P3-4-ext3**: config integration + `config_hash` شامل allowed_regimes
- **P3-5 Regime Benchmark**: `scripts/benchmark_regime.py` با regression guard
- بک‌تست رویدادمحور با اسپرد/کمیسیون/سوآپ/لغزش، Stop-first و ورود در کندل بعد
- تفکیک هزینه‌ها (AC-07)، OOS سه‌بخشی + Embargo (AC-08)، Walk-forward، PBO، DSR، Monte Carlo
- گزارش Markdown/HTML با نمودار SVG + بخش regime + بخش calibration

### اجرا (P6 — MVP-2)
- **P6-1 PaperBroker**: fault injection (reject/timeout/partial) + Reconciliation
- **P6-2 Phase Guard E2E**: تست کامل READ_ONLY → PAPER
- **P6-3 Reconciliation CLI**: `reconcile`, `orders list/show`
- **P6-4**: `--allowed-regimes` shortcut
- **P6-5 Paper Trading E2E**: مسیر کامل روی DB فایل‌محور (persistence, reconciliation)
- `ExecutionService.submit`: مجدداً Kill Switch و TTL را enforce می‌کند (FIX-P0-4)
- **FIX-P6-5**: `target = broker_order.status` (نه hardcoded FILLED/PARTIAL)
- **FIX-P6-5**: state machine گذارهای `ACKNOWLEDGED → UNKNOWN` و `UNKNOWN → terminal` را مجاز می‌داند

### زیرساخت (P4، P5، P7)
- **P4-1 Storage Protocol**: `DatabaseProtocol` + `InMemoryDatabase`
- **P4-2 Migration Framework**: `up/down/history` + `_ensure_meta_table`
- **P4-3 Postgres Adapter**: `PostgresDatabase` skeleton با SQL translation
- **P4-3-ext**: `postgres_schema.sql` (TIMESTAMPTZ/JSONB/BIGSERIAL) + idempotent migration runner
- **P5-1 Metrics Registry**: counters/gauges/histograms + Prometheus format
- **P5-2 Health/Ready/Live**: `/api/v1/health/live`, `/api/v1/health/ready`
- **P5-3 Structured Logging**: Bearer/Basic/JWT/API-key redaction + Error JSONL + rotation
- **P5-4 Metrics Dashboard**: `/metrics-dashboard` (Persian RTL, uptime, tables, histograms)
- **P7 CI**: GitHub Actions (Ubuntu + Windows, Python 3.11 + 3.12) با lint، typecheck، test، coverage، smoke، benchmark

### API، UI، امنیت، ممیزی
- API نسخه‌دار `/api/v1` با RBAC، Idempotency، Rate Limit، خطای ساختاریافته و OpenAPI
- **FIX-P1-3**: `/market-data/candles` با `order=asc|desc`
- **FIX-P2-2**: 405 با `Allow` header برای متدهای ناشناخته
- **FIX-P2-3**: drain oversized body قبل از 413
- **FIX-P0-3**: `SessionRepository.revoke_all` روی تغییر رمز
- **FIX-P1-2**: شمارش شکست‌های متوالی ورود (clock تزریقی)
- **FIX-P0-4**: Kill Switch + TTL مجدد در `submit`
- **FIX-P1-1**: Idempotent replay (بدون Side-effect تکراری)
- **FIX-P0-5**: `_correlations` فقط از primary source
- داشبورد فارسی RTL: تحلیل، سناریو، ریسک، بک‌تست، عملیات
- PBKDF2 + TOTP + نشست‌های قابل ابطال
- Audit زنجیره‌هش فقط‌افزودنی + Transactional Outbox
- بازتولیدپذیری: `run_id`/`result_hash` مشتق از Snapshot، Config و نسخه‌ها (AC-02)

## ۳. نتیجه اجرای دمو (Seed=7، EURUSD/H1)

### Baseline (همه رژیم‌ها)

| مورد | مقدار |
|---|---|
| کندل‌ها | ۴۶۵۸ (۲۰۲۶-۰۲-۰۱ تا ۲۰۲۶-۱۰-۳۰) |
| کیفیت داده | PASS (۰ قرنطینه، ۰ شکاف) |
| بک‌تست | `bt_e6ecc4adfd1b07375ea6ed0a` |
| معاملات | ۳۴۷ (Win 51.3٪، PF 1.05، Net +66.92، MDD 1.48٪) |
| Sharpe / Sortino / Calmar | 0.40 / 0.57 / 0.62 |
| DSR (trials=1) | 0.634 |
| هزینه‌ها | اسپرد 93.39 + کمیسیون 59.92 + لغزش 51.36 + سوآپ −7.06 = 197.61 |

### Filtered (TRENDING_UP + TRENDING_DOWN)

| مورد | مقدار |
|---|---|
| بک‌تست | `bt_375033d48638f18acac676fc` |
| معاملات | ۳۰۳ (Win 52.5٪، PF 1.14، Net **+163.46**، MDD 1.62٪) |
| Sharpe / Sortino / Calmar | **1.13** / 1.62 / 1.61 |
| DSR (trials=1) | **0.814** |
| سیگنال‌های ردشده | ۶۳۷ |
| **Delta** | **net +144.2٪، sharpe +181.6٪، dsr +28.4٪** |

### تفکیک عملکرد بر اساس رژیم بازار

| رژیم | تعداد | نرخ برد | میانگین PnL | مجموع PnL |
|---|---|---|---|---|
| TRENDING_UP | ۱۶۵ | ۴۹.۷٪ | +۰.۳۴ | +۵۵.۷ |
| TRENDING_DOWN | ۱۰۴ | **۵۸.۷٪** | **+۰.۶۰** | **+۶۲.۹** |
| LOW_VOL | ۷۱ | ۴۷.۹٪ | −۰.۳۹ | −۲۷.۵ |
| RANGING | ۶ | ۱۶.۷٪ | **−۳.۹۷** | −۲۳.۸ |
| HIGH_VOL | ۱ | ۰٪ | −۰.۴۰ | −۰.۴ |

> این اعداد خروجی یک baseline روی داده شبیه‌سازی‌شده است و مبنای تصمیم سرمایه‌گذاری نیست. Forward Test الزامی است.

## ۴. آزمون و پذیرش

## بازبینی P0/P1 — 2026-11-03

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

## فاز ۷ — تجاری، اشتراک، امنیت و حقوق داده (v1.6.0) — نسخه نهایی 2026-11-11

### چندمستاجری
- `tenant_id` در `users`, `analysis_runs`, `scenarios`, `risk_decisions`, `order_intents` و اعمال سطری در Repository/Service/API.
- دسترسی به داده مستاجر دیگر `NOT_FOUND` (404) و مستاجر غیرفعال `TENANT_INACTIVE` (403) می‌دهد.
- شناسه تحلیل و سناریو برای مستاجر غیرپیش‌فرض شامل `tenant_id` است؛ نقص تصادم شناسه سناریو در آزمون جداسازی کشف و رفع شد.

### اشتراک و سهمیه
- پلن‌ها: `basic` (۳ کاربر/۵۰۰ تحلیل روزانه/۵۰ سناریو)، `pro` (۲۰/۵۰۰۰/۵۰۰)، `enterprise` (نامحدود).
- `quota_overrides` در سطح مستاجر؛ بررسی در ساخت کاربر، اجرای تحلیل و ساخت سناریوی فعال؛ خطای `QUOTA_EXCEEDED` (429) با جزئیات سقف/مصرف.
- مستاجر پیش‌فرض روی `enterprise` نگه داشته می‌شود تا نصب‌های موجود محدود نشوند.

### API و CLI
- `GET /api/v1/tenant`, `/tenant/export`, `/tenant/retention` برای کاربر؛
- `GET /api/v1/tenants` و export/retention و `POST /api/v1/tenants/{id}` برای `tenant.admin`؛
- `python -m fxars.cli.main tenants list|create|set-plan` و `security-audit`.

### حقوق داده
- خروجی JSON شامل کاربران (بدون هش رمز/TOTP)، تحلیل‌ها، سناریوها، تصمیم‌های ریسک و سفارش‌های مستاجر.
- گزارش نگهداری شامل سیاست‌ها و شمارش واقعی؛ هیچ حذف خودکاری انجام نمی‌شود.

### ممیزی امنیت (دروازه فاز ۷)
- بررسی MFA نقش‌های حساس، TTL نشست، محدودیت نرخ، کلید امنیتی (بدون چاپ مقدار)، قدرت PBKDF2، ستون‌های `tenant_id`، زنجیره ممیزی، پوشش رخدادها، نشت اسرار در payload و حقوق داده.
- اجرا روی پایگاه تولیدی پس از پشتیبان‌گیری و با مجوز اپراتور: `ok=true`, `pass=9`, `warn=1` (کلید dev)، `fail=0`، زنجیره ۱۹۱۷ رکورد معتبر، همه جدول‌ها دارای `tenant_id` و بدون ردیف بی‌مستاجر.
- نقص کشف‌شده در بازبینی نهایی: آزمون بنچمارک روی پایگاه تولیدی می‌نوشت؛ اسکریپت به داده دمو در حافظه منتقل شد و اجرای مجدد کل مجموعه هیچ رکورد آزمونی در تولید ثبت نکرد.

### وضعیت نهایی و شواهد JSON
- گزارش ماشین‌خوان: `reports/phase7-20261111.json` (تولید `2026-11-11T04:34:13Z`، قرائت فقط‌خواندنی از `data/fxars.db`).
- دروازه‌ها: A تا E و G عبور کرده‌اند؛ F با وضعیت `technically_complete_pending_operator_approval`.
- مستاجر فعلی: `default` با پلن `enterprise` و وضعیت فعال؛ ۴ کاربر، ۵۱۵ تحلیل، ۲۷۷ سناریو، ۱۳۶ تصمیم ریسک، ۶۵ سفارش.
- ممیزی امنیت: `ok=true`، `pass=9`، `warn=1`، `fail=0`، `score=0.9`؛ خروجی خام در `reports/phase7-security-audit-20261111.json`.

### Forward Test (دروازه F)
- اجرا روی کپی سازگار از دیتابیس عملیاتی (SQLite backup API، مبدأ فقط-خواندنی)، EURUSD/H1 از منبع اصلی `mt5` (داده واقعی بروکر؛ `demo_feed` با اولویت پایین‌تر کنار گذاشته شد)، `warmup=300`، ۲۵۶ گام از 2026-10-23T10:00Z تا 2026-11-09T03:00Z.
- نتیجه: `PASS`، صفر خطا، صفر نقض look-ahead؛ LONG=76، SHORT=104، NO_TRADE=76؛ سناریوها WATCH=102 و DRAFT=78.
- اجرای اولیه با `warmup=200` به‌دلیل `min_bars=220` در گام‌های ابتدایی داده ناکافی داشت؛ warmup به 300 افزایش یافت.
- شواهد: `reports/forward-test-20261111.md`, `reports/forward-test-20261111-w300.json` (دیتابیس موقت پس از آزمون حذف شد).

### آزمون
- `tests/test_tenant_isolation.py` (۵)، `tests/test_tenant_quota.py` (۹)، `tests/test_tenant_rights.py` (۱۰) — همه سبز.
- `tests/test_closed_trades.py` (۱۴) و آزمون‌های هیستوری بسته‌شدن در `tests/test_mt5_broker.py` (۴) — همه سبز.
- `tests/test_kms.py` (۱۸) برای KMS محلی/محیطی، چرخش کلید، SecretBox نسخه‌دار و لنگر ممیزی؛ ۳ آزمون تنظیمات KMS.
- `tests/test_phase_runtime.py` (۷) برای اعمال فاز بدون ری‌استارت، نگاشت ADVISOR، بروکر و مسیر API؛ `tests/test_live_daemon.py` (+۳ و +۱ reload تنظیمات معاملات) برای reload فاز/تنظیمات در daemon؛ `tests/test_risk.py` (+۳) برای پیام‌های مشخص رد ریسک.
- `tests/test_trading_defaults.py` (۱۵) برای پروفایل‌های سرمایه، سقف‌گذاری سیاست، پله‌های حجم، اعتبارسنجی تنظیمات، coercion و اعمال API/پلتفرم.
- اجرای کامل: **659 آزمون، OK (7 skip)**.

## سند تکمیلی ۱.۱ — تصمیم، ریسک و حاکمیت (v1.8.0) — 2026-11-12

### دامنه اعمال‌شده
- **No-Trade First و شفافیت تصمیم**: DTS پنج‌مؤلفه‌ای با وضعیت `TRUSTED/DEGRADED/UNTRUSTED` و دروازه `DATA_UNTRUSTED`؛ استناد هر تصمیم به شواهد، رژیم و استاندارد خروجی.
- **DTS → گراف شواهد → امتیاز ترکیبی → بودجه عدم‌قطعیت → Provenance** در یک مسیر واحد (`fxars/services/analysis.py`) و ثبت `analysis_meta` در `AnalysisRun.decision`.
- **حاکمیت**: Policy Registry نسخه‌دار با تأیید مستقل، Model Registry با Tier 0–3 و Model Card، عدم مجاز بودن Tier 3 در MVP و الزام Shadow/OOS/تأیید مستقل برای Tier 2، ثبت Drift.
- **ایمنی اجرا**: Kill Switch سه‌سطحی (`SYSTEM/MODULE/ACCOUNT`)، چرخه قفل ریسک `NORMAL→WARNING→LOCKED_DAILY→LOCKED_WEEKLY→KILL_SWITCH→MANUAL_REVIEW`، کنترل زیان هفتگی (سه‌برابر سقف روزانه) و کنترل سشن بازار.
- **پژوهش**: دروازه پذیرش OOS با بررسی‌های عددی و الگوهای ضدّی؛ فرمان `research-gate [--strict]`.
- **قابلیت‌های محصول**: دفتر تصمیم، بازپخش خلاف واقع، پیش‌مرگ، نقشه حرارتی سناریو، حالت چالش، تب «هوشمندی تصمیم» در داشبورد و endpointهای API با RBAC/tenant.

### آزمون‌های جدید (۷۳ آزمون)
| فایل | تعداد | پوشش |
|---|---|---|
| `tests/test_decision_policy.py` | ۱۹ | اعتبار سیاست، DTS، بودجه عدم‌قطعیت، امتیاز ترکیبی، گراف شواهد و `analysis_meta` |
| `tests/test_governance.py` | ۱۷ | زنجیره Provenance و کشف دستکاری، رجیستری سیاست، Model Card و Drift |
| `tests/test_risk_lock.py` | ۱۷ | چرخه قفل، زیان هفتگی واقعی، سشن بازار، Kill Switch سه‌سطحی |
| `tests/test_intelligence.py` | ۱۲ | دفتر تصمیم، نقشه حرارتی، پیش‌مرگ، بازپخش، چالش و APIهای تکمیلی |
| `tests/test_acceptance_gates.py` | ۸ | معیارهای پذیرش، الگوهای ضدّی، `evaluate_run` و سیم‌کشی CLI |

### اصلاحات جانبی
- `KillSwitch.all_status` ستون ناموجود `payload` را می‌خواند؛ به `key` اصلاح شد تا سطح‌بندی جدید بدون خطا کار کند.
- `RiskService` اکنون زیان هفتگی را از معاملات بسته‌شده محاسبه و قفل ریسک را پیش از ارزیابی به‌روزرسانی می‌کند؛ `RiskGate` این وضعیت را به‌صورت Fail-Closed اعمال می‌کند.
- کنترل سشن بازار با مهلت `data_grace_seconds` نسبت به آخرین بازگشایی، تا مرز بسته‌شدن هفته باعث هشدار کاذب نشود.

### اجرای نهایی
- `python -m unittest discover -s tests -t .` → **737 آزمون، OK (7 skip)**.

### اصلاح ورود معامله در حساب ۱۰۰ دلاری — 2026-11-12
- **ریشه مشکل:** با اکوئیتی ۱۰۰.۳۵ و ریسک ۵٪، بودجه ریسک ۵.۰۲ دلار است؛ حداقل ضرر ۰.۰۱ لات روی استاپ ۸۴ پیپی H1 برابر ۸.۴۴ دلار (۸.۴٪) است، بنابراین حجم صفر و `POSITION_SIZE_INVALID` می‌شد. تنها سفارش پر شده قبلی (`18:07`) دستی با نقش admin بود، نه ربات.
- **سقف حجم:** `_cap_decision_volume` حجم تأییدشده را به `max_volume_per_order` کاهش می‌دهد (مثلاً ۰.۱۷ → ۰.۰۴) و ریسک تصمیم را متناسب اصلاح می‌کند؛ سقف زیر حداقل لات همچنان Fail-Closed است.
- **هم‌راستایی سناریو:** `ExecutionService` از طریق `_scenario_trigger_required` تنظیم `require_triggered_scenario=false` فاز را رعایت می‌کند؛ پیش از این daemon ورود ARMED را مجاز اعلام می‌کرد اما ساخت سفارش `PHASE_VIOLATION` می‌داد.
- **پیکربندی دمو:** `config/phase.json` روی `M15` محدود شد تا سیگنال‌های H1 با استاپ بزرگ در حساب کوچک رد نشوند؛ ریسک ۵٪ و سقف ۰.۰۴ حفظ شد. `config/live.json` نیز به `timeframes=["M15"]` و `primary_timeframe="M15"` تغییر کرد تا daemon واقعی هم فقط M15 را تحلیل کند.
- **آزمون:** `tests/test_volume_cap.py` (۵ آزمون) و اجرای کامل **737 آزمون، OK (7 skip)**.

### استراتژی‌های دستی کاربر (M5) — v1.9.0
- **محل پیاده‌سازی:** `fxars/live/strategy_selector.py`؛ فهرست `STRATEGIES` دو عضو جدید گرفت و `select_best_strategy(..., strategy=...)` انتخاب دستی را بر امتیاز خودکار مقدم می‌داند. انتخاب خالی همان رفتار قبلی (بهترین امتیاز) است.
- **EMA20/FullBody:** کندل M5 با بدنه برابر دامنه (بدون سایه)، بدنه ۱۰ تا ۲۰ پیپ؛ سبز و کاملاً بالای EMA20 ⇒ خرید با SL دو پیپ زیر کندل و TP دو برابر بدنه؛ قرمز و کاملاً زیر EMA20 ⇒ فروش متقارن.
- **H&S/Reversal:** سه سوئینگ متوالی هم‌نوع با ساختار شانه-سر-شانه و تأیید دو دره/قله میانی؛ معکوس = سر پایین‌تر و شانه راست بالاتر از شانه چپ (خرید)، معمولی = سر بالاتر و شانه راست پایین‌تر (فروش). تریگر: کندل سبز بالای EMA20 یا قرمز زیر آن. SL دو پیپ آن‌سوی شانه چپ و TP ۲۰ پیپ (برای فروش، ۲۰ پیپ زیر ورود).
- **API:** پارامتر اختیاری `strategy` در سه مسیر `/api/v1/strategy/analyze|trade|trade_multi`؛ نام ناشناخته یا تایم‌فریم غیر M5 برای استراتژی‌های کاربر با خطای ۴۰۰ رد می‌شود. پاسخ شامل `available` و `selected` است.
- **داشبورد:** انتخابگر استراتژی، ذخیره انتخاب در `localStorage`، قفل تایم‌فریم روی M5 و نمایش استراتژی در نتیجه تحلیل/تأیید سفارش.
- **مجوز فاز:** `automated_limited.timeframes` شامل `M5` شد (در کنار M15 و H1 موجود) تا سفارش‌های این استراتژی‌ها از `execution_block_reason` عبور کنند؛ بدون این مورد پاسخ `TIMEFRAME_NOT_ALLOWED` بود.
- **آزمون:** `tests/test_user_strategies.py` (۱۹ آزمون) و اجرای کامل **756 آزمون، OK (7 skip)**.

### اصلاح کلید Kill Switch — v1.9.1
- **ریشه مشکل:** در تب «عملیات» فقط دکمهٔ «فعال» وجود داشت و هر کلیک، Kill Switch را دوباره فعال می‌کرد؛ امکان غیرفعال‌سازی فقط در تب «هوش تصمیم» و با دلیل اجباری بود. Audit نشان داد همهٔ رخدادها `activated` هستند و هیچ `deactivated` ثبت نشده است؛ به همین دلیل معاملات قفل می‌ماند.
- **اصلاح UI:** کارت عملیات به کلید دوطرفه با دکمه‌های «فعال‌سازی» و «غیرفعال‌سازی»، نمایش وضعیت/دلیل جاری و تأیید پیش از غیرفعال‌سازی تبدیل شد. وضعیت در تب «معاملات» و نشان‌گر هدر با `refreshKillState()` هم‌گام می‌شود.
- **آزمون:** ۱ آزمون چرخهٔ HTTP فعال/غیرفعال و به‌روزرسانی `meta` در `tests/test_security.py`؛ ۳ آزمون رگرسیون UI در `tests/test_dashboard_killswitch_ui.py`. اجرای کامل: **760 آزمون، OK (7 skip)**.

### تنظیمات هوشمند بدون سقف اجباری — v1.10.0
- **محدودیت‌های برداشته‌شده:** `TS_TIMEFRAMES` در داشبورد کامل شد (`M5`, `M15`, `H1`, `H4`, `D1`) و `renderTsInstruments` دیگر فقط ده نماد پیشنهادی را نشان نمی‌دهد؛ همهٔ نمادهای پایگاه داده (به‌جز `DXY` که شاخص مرجع است) در فهرست «نمادهای مجاز» می‌آیند: `BTCUSD`، `ETHUSD`، `XAGUSD` هم قابل انتخاب‌اند.
- **اعتبارسنجی نرم:** `validate_automated_settings_soft` در `fxars/config/trading_defaults.py` خطاهای ساختاری (صفر/منفی، پوزیشن یا معاملهٔ روزانهٔ کمتر از ۱، تایم‌فریم ناشناخته، نماد بدون مشخصات) را از هشدارهای سیاست جدا می‌کند. عبور از سقف ریسک/زیان/افت/پوزیشن/معامله/اسپرد/حجم و انتخاب نماد خارج از فهرست پیشنهادی فقط هشدار است.
- **جریان تأیید:** `Platform.apply_trading_settings(..., confirm_warnings=False)` در صورت وجود هشدار `requires_confirmation=True` برمی‌گرداند و فایل `phase.json` را نمی‌نویسد؛ فقط تکرار با `confirm_warnings=true` (از داشبورد پس از `confirm()` حاوی فهرست هشدارها) ذخیره و در همان اجرا اعمال می‌شود. رخداد `TRADING_SETTINGS_CHANGED` همراه `warnings` ممیزی می‌شود.
- **Fail-safe:** `RiskService`/`RiskGate` تغییر نکرده‌اند و سقف‌های سخت سیاست را مستقل از تنظیمات، هنگام ارزیابی و ارسال سفارش اعمال می‌کنند؛ متن راهنمای فرم هم همین را به کاربر می‌گوید.
- **رفع خطای JS:** رشته‌های `join("\n")`/پیام تأیید در `DASHBOARD_HTML` باید `\\n` نوشته شوند (رشتهٔ پایتون غیر-raw است)؛ نسخهٔ قبلی شکست خط واقعی داخل رشته تولید می‌کرد و کل اسکریپت داشبورد با `Invalid or unexpected token` از کار می‌افتاد.
- **آزمون:** ۵ آزمون UI در `tests/test_dashboard_trading_settings_ui.py` و آزمون‌های حالت نرم/جریان تأیید در `tests/test_trading_defaults.py`. اجرای کامل: **770 آزمون، OK (7 skip)**.

### فیلتر روند تایم‌فریم بالاتر (H1) برای استراتژی‌های M5 — v1.11.0
- **قانون:** جهت روند با EMA50 روی کندل‌های **بسته‌شدهٔ** H1 تعیین می‌شود؛ برای هر کندل M5 فقط آخرین کندل H1 با `close_time <= open_time` لحاظ می‌شود، بنابراین در بک‌تست و سیگنال زنده هیچ نگاهی به آینده وجود ندارد.
- **دامنه اعمال:** فقط دو استراتژی دستی `EMA20/FullBody` و `H&S/Reversal` (زمانی که تایم‌فریم M5 است)؛ ورود هم‌جهت با روند (LONG در روند صعودی، SHORT در روند نزولی) مجاز و ورود خلاف روند حذف می‌شود. چهار استراتژی خودکار قبلی بدون تغییر می‌مانند.
- **پیاده‌سازی:** `TREND_TIMEFRAME`/`TREND_EMA_PERIOD` و توابع `trend_history_bars`, `_trend_directions`, `_trend_filtered` در `fxars/live/strategy_selector.py`؛ بک‌تست و `_latest_signal` از همان زنجیره استفاده می‌کنند تا امتیاز و سیگنال هم‌خوان بمانند.
- **Fail-closed:** اگر تاریخچهٔ H1 خالی باشد یا EMA در دسترس نباشد، جهت `None` می‌شود و ورود مسدود است (`trend_filter.applied=true, direction=null`)؛ نبودِ داده هرگز به معنی «مجاز» نیست.
- **API:** سه مسیر `/api/v1/strategy/analyze|trade|trade_multi` برای M5 به‌اندازهٔ `trend_history_bars(bars) = min(5000, max(120, bars//12 + 60))` کندل H1 از همان فید می‌گیرند؛ شکست در دریافت H1 پاسخ `503 BROKER_UNAVAILABLE` می‌دهد. همهٔ پاسخ‌ها فیلد `trend_filter: {timeframe, applied, direction}` دارند و در صورت رد سیگنال، `reason` علت ناسازگاری با روند را ذکر می‌کند.
- **داشبورد:** در نتیجه تحلیل، ردیف «فیلتر روند H1» با وضعیت صعودی (خرید مجاز)، نزولی (فروش مجاز) یا نامشخص (ورود مسدود) نمایش داده می‌شود؛ راهنمای انتخاب استراتژی هم به اجرای هم‌جهت با روند H1 اشاره می‌کند.
- **شاهد دادهٔ واقعی (EURUSD/M5، ۲۰۰۰ کندل):** استراتژی H&S/Reversal با فیلتر: معاملات 97→65، نرخ برد 62%→74%، Profit Factor 3.02→6.41، حداکثر افت 6.79%→3.98% و امتیاز 0.986→0.992. استراتژی EMA20/FullBody در همین بازه معامله‌ای تولید نکرد.
- **آزمون:** ۹ آزمون در `TrendFilterTests` (عدم نگاه به آینده، جهت نزولی، مسدودسازی سیگنال هم‌جهت‌نبودن، fail-closed برای تاریخچهٔ خالی، پوشش تعداد کندل H1 و رفتار API) و ۲ آزمون رگرسیون UI در `StrategyTrendFilterUiTests`؛ اجرای کامل **781 آزمون، OK (7 skip)**.
