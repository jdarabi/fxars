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
| Decision Intelligence | DTS، گراف شواهد، امتیاز ترکیبی، عدم‌قطعیت، ژورنال/بازپخش/پیش‌مرگ/چالش | صدور سفارش |
| Governance | Policy Registry، Model Card/Tier، Provenance زنجیره‌ای | دور زدن ممیزی |
| Risk | sizing، محدودیت‌ها، RiskDecision، قفل ریسک، Kill Switch سطح‌دار | مصرف داده بدون قرارداد |
| Research | بک‌تست، OOS، Walk-forward، گزارش | نگاه به آینده |
| Execution | OrderIntent، آداپتر، تطبیق | بازتعریف تحلیل/ریسک |
| Identity | کاربر، نقش، مجوز، نشست، MFA | اعمال مجوز فقط در UI |
| Tenancy | جداسازی `tenant_id`، پلن/سهمیه اشتراک، حقوق داده، ممیزی امنیت | دور زدن سهمیه در سرویس |
| Audit & Outbox | ممیزی زنجیره‌ای، رویداد | ثبت اسرار |

## ۳. جریان اجرای تحلیل

1. `AnalysisService.run` کندل‌های **بسته و قابل استفاده** تا `available_at ≤ as_of` را می‌خواند.
2. تازگی داده با تقویم سشن سنجیده می‌شود؛ کهنه ⇒ اجرای `STALE` و `NO TRADE/DATA_STALE`.
3. `snapshot_id` از محتوای کندل‌ها و `config_hash` از پیکربندی ساخته می‌شود؛ `run_id` از این دو + زمان تصمیم.
4. `compute_data_trust` پنج مؤلفه DTS را می‌سنجد؛ `UNTRUSTED` ⇒ `NO_TRADE/DATA_UNTRUSTED`.
5. `AnalysisEngine` اندیکاتورها و ۸ ماژول را اجرا و `Evidence` تولید می‌کند.
6. `build_evidence_graph` روابط/تکرار شواهد و `composite_score` امتیاز `S = Σw·E·R·F − P_conflict` را می‌سازد.
7. `compute_uncertainty` بودجه `U` را می‌سنجد؛ عبور از سقف ⇒ `NO_TRADE/UNCERTAINTY_TOO_HIGH`.
8. `aggregate_evidence` شواهد را در خانواده‌ها تجمیع و تصمیم/NO TRADE صادر می‌کند.
9. `ScenarioBuilder` سناریوی جهت‌دار با Trigger/Invalidation/Expiry/Stop/Targets می‌سازد.
10. `AnalysisRun`، Evidenceهای پنجره اخیر، سناریو، Transition و `DecisionProvenance` در یک تراکنش ذخیره و Audit/Outbox ثبت می‌شوند.

زمان تصمیم = `latest.available_at` (نه ساعت دیواری)؛ تازگی نسب به ساعت درخواست سنجیده می‌شود. این تفکیک از نگاه به آینده و از انقضای کاذب سناریو در تعطیلات جلوگیری می‌کند.

### ۳-۱. جریان ریسک، قفل و حاکمیت

1. `RiskService.evaluate` زیان روزانه و زیان هفتگی محقق‌شده (`closed_trades`) را به کسر سرمایه تبدیل می‌کند.
2. `RiskLockMachine.evaluate` وضعیت را به‌روز می‌کند؛ گذارهای مسدودکننده در `system_state` و Audit ثبت می‌شوند.
3. `RiskGate` کنترل‌های `risk_lock_clear`، `weekly_loss_within_limit`، `market_open` و کنترل‌های قبلی را اجرا می‌کند.
4. `ExecutionService` فقط با RiskDecision تأییدشده/تازه، قفل باز، Kill Switch غیرفعال و فاز مجاز سفارش می‌سازد.
5. `PolicyRegistry` و `ModelRegistryService` نسخه فعال و شرایط انتشار را نگه می‌دارند؛ `DecisionProvenanceStore` زنجیره هش تحلیل‌ها را حفظ می‌کند.

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
- `order_intents`, `broker_orders`, `fills`, `closed_trades` (فاز اجرا)
- `system_state` (Kill Switch و قفل ریسک)، `locked_test_access`, `model_registry`, `model_drift`
- `decision_provenance` (زنجیره هش)، `policy_registry`, `decision_journal`, `scenario_challenges`

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
