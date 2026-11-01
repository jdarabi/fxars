# معماری سامانه FX-ARS

سند مبنا: `FX-ARS-SRS-ARCH-002` — نسخه ۲.۱

## ۱. سبک معماری

**Modular Monolith**: یک برنامه قابل استقرار با مرزهای دامنه‌ای صریح. وابستگی بین ماژول‌ها فقط از طریق قرارداد/سرویس است؛ لایه دامنه به SQLite/HTTP وابسته نیست. زیرساخت در `Platform` (Composition Root) تزریق می‌شود.

```
CLI / HTTP API / Dashboard
        │
Application Services (analysis, scenarios, risk, research, execution)
        │
Domain (models, enums, state machines, aggregation, sizing)
        │
Ports/Repositories ──► Infrastructure (SQLite, CSV/Synthetic feed, Paper broker)
```

## ۲. مرزهای دامنه

| ماژول | مسئولیت | ممنوعیت |
|---|---|---|
| Market Data | دریافت، اعتبارسنجی، قرنطینه، ذخیره، کیفیت، Lineage | منطق سیگنال/سفارش |
| Instrument & Calendar | مشخصات قراردادی، سشن، تعطیلات، نگاشت نماد | تحمیل منبع به تحلیل |
| Market Analysis | ویژگی‌ها و Evidence | ارسال سفارش |
| Scenario & Decision | تجمیع شواهد، سناریو، NO TRADE | دور زدن ریسک |
| Risk | sizing، محدودیت‌ها، RiskDecision، Kill Switch | مصرف داده بدون قرارداد |
| Research | بک‌تست، OOS، Walk-forward، گزارش | نگاه به آینده |
| Execution | OrderIntent، آداپتر، تطبیق | بازتعریف تحلیل/ریسک |
| Identity | کاربر، نقش، مجوز، نشست، MFA | اعمال مجوز فقط در UI |
| Audit & Outbox | ممیزی زنجیره‌ای، رویداد | ثبت اسرار |

## ۳. جریان اجرای تحلیل

1. `AnalysisService.run` کندل‌های **بسته و قابل استفاده** تا `available_at ≤ as_of` را می‌خواند.
2. تازگی داده با تقویم سشن سنجیده می‌شود؛ کهنه ⇒ اجرای `STALE` و `NO TRADE/DATA_STALE`.
3. `snapshot_id` از محتوای کندل‌ها و `config_hash` از پیکربندی ساخته می‌شود؛ `run_id` از این دو + زمان تصمیم.
4. `AnalysisEngine` اندیکاتورها و ۸ ماژول را اجرا و `Evidence` تولید می‌کند.
5. `aggregate_evidence` شواهد را در خانواده‌ها تجمیع و تصمیم/NO TRADE صادر می‌کند.
6. `ScenarioBuilder` سناریوی جهت‌دار با Trigger/Invalidation/Expiry/Stop/Targets می‌سازد.
7. `AnalysisRun`، Evidenceهای پنجره اخیر، سناریو و Transition در یک تراکنش ذخیره و Audit/Outbox ثبت می‌شوند.

زمان تصمیم = `latest.available_at` (نه ساعت دیواری)؛ تازگی نسب به ساعت درخواست سنجیده می‌شود. این تفکیک از نگاه به آینده و از انقضای کاذب سناریو در تعطیلات جلوگیری می‌کند.

## ۴. مدل اطلاعاتی (SQLite)

- `instruments`, `data_sources`, `symbol_mappings`
- `candles` با PK `(instrument, source, timeframe, open_time, revision)` و `candle_revision_log` / `candle_quarantine` / `raw_payloads` (append-only)
- `economic_events` با revision
- `analysis_runs`, `evidences`
- `scenarios`, `scenario_transitions`
- `risk_decisions`, `account_snapshots`
- `data_quality_runs`, `backtest_runs`
- `audit_events` (Trigger ضد UPDATE/DELETE)، `outbox`, `outbox_consumed`
- `users`, `sessions`, `login_attempts`, `idempotency_keys`
- `order_intents`, `broker_orders`, `fills` (فاز اجرا)
- `system_state` (Kill Switch)، `locked_test_access`, `model_registry`

قیمت/پول/حجم/نرخ همه `Decimal` و به‌صورت رشته ذخیره می‌شوند. زمان‌ها ISO-8601 UTC با `Z`.

## ۵. رویداد و تراکنش

الگوی **Transactional Outbox**: تغییر دامنه + رکورد Outbox در یک تراکنش؛ مصرف‌کننده idempotent با `outbox_consumed`. همه رویدادها `event_id`, `event_type`, `schema_version`, `occurred_at`, `correlation_id`, `payload` دارند.

## ۶. بازتولیدپذیری

- `data_snapshot_id`: هش محتوای کندل‌ها (بدون `ingested_at`)
- `config_hash`: ریسک + تحلیل + کیفیت داده + نسخه‌ها
- `result_hash`: تصمیم + شواهد ذخیره‌شده
- `analysis_run_id`: مشتق از snapshot/config/code/زمان تصمیم
- اجرای دوباره با ورودی یکسان: همان `run_id` و `result_hash`؛ اختلاف ⇒ `REPRODUCIBILITY_ERROR`

## ۷. امنیت

- رمز: PBKDF2-HMAC-SHA256 (۲۱۰هزار تکرار) + Salt
- TOTP برای نقش‌های ADMIN/RISK_MANAGER/OPERATOR
- نشست: توکن تصادفی، ذخیره فقط هش، انقضا و ابطال
- RBAC سمت سرور؛ Audit برای ورود/تغییر سیاست/عملیات حساس
- اسرار در لاگ redact می‌شوند؛ TOTP با `SecretBox` رمزنگاری‌شده ذخیره می‌شود

## ۸. استقرار

MVP-1 تک‌فرآیندی با SQLite (WAL) است. برای تولید: PostgreSQL، اجرای API پشت Reverse Proxy TLS، Secret Manager، پشتیبان‌گیری خارج از میزبان و پایش. مرزهای Repository مهاجرت را بدون تغییر دامنه ممکن می‌کند.
