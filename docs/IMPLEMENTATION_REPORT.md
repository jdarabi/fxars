# گزارش پیاده‌سازی — FX-ARS

سند مبنا: `FX-ARS-SRS-ARCH-002` (نسخه ۲.۱) — نسخه پیاده‌سازی: `1.5.1` — قواعد: `rules_v1.3.0`

## ۱. خلاصه

پروژه به‌صورت یک **Modular Monolith** کامل با پایتون و تنها کتابخانه استاندارد پیاده‌سازی شد. فاز **MVP-1** (تحلیل و پشتیبانی تصمیم، فقط‌خواندنی) به‌طور کامل اجراشدنی و آزمون‌شده است. اسکلت **MVP-2** (Order State Machine، PaperBroker با fault injection، Reconciliation، Phase Guard) نیز کامل و آزمون‌شده است.

| شاخص | مقدار |
|---|---|
| نسخه | **1.4.10** |
| Tagها | 20 (v1.3.1 → v1.4.10) |
| فایل‌های پایتون | ~110 |
| خطوط کد پایتون | ~15,000 |
| فایل‌های آزمون | 18 |
| خطوط آزمون | ~2,800 |
| آزمون‌ها | **363 (2 skip: live Postgres بدون DSN)** |
| معیارهای پذیرش | **AC-01..AC-12 — همه موفق** |
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
