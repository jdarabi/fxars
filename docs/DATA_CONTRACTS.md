# قراردادهای داده و کیفیت داده

## ۱. Candle

| فیلد | نوع | قاعده |
|---|---|---|
| instrument_id | string | شناسه داخلی نماد |
| source_id | string | منبع داده |
| timeframe | M1..W1 | شبکه زمانی |
| bar_open_time_utc | ISO-8601 UTC | هم‌تراز با شبکه |
| open/high/low/close | Decimal (string) | مثبت؛ High ≥ max(O,C)، Low ≤ min(O,C) |
| tick_volume | int/null | غیرمنفی؛ فقط فعالیت همان منبع |
| spread | Decimal/null | غیرمنفی، واحد قیمتی |
| is_closed | bool | تحلیل قطعی فقط کندل بسته |
| quality_status | VALID/SUSPECT/INVALID | INVALID وارد تحلیل نمی‌شود |
| source_revision | string/null | شناسه اصلاح منبع |
| ingested_at / available_at | UTC | زمان ورود / زمان دسترس‌پذیری واقعی |
| revision | int | نسخه رکورد در سامانه (اصلاح ⇒ +1) |

نمونه در API: `GET /api/v1/market-data/candles`.

## ۲. EconomicEvent (Bitemporal)

`event_id`, `event_time_utc`, `published_at`, `available_at`, `country`, `currency`, `indicator`,
`actual`, `forecast`, `previous`, `importance`, `unit`, `revision_of`, `source_id`.

قواعد:
- بک‌تست فقط رویدادهایی را می‌بیند که `available_at ≤ زمان تصمیم` دارند.
- اصلاح داده نسخه قبلی را حذف نمی‌کند؛ revision جدید ثبت می‌شود.
- Blackout بر مبنای `event_time` (تقویم از پیش معلوم) و اهمیت رویداد است.

## ۳. Evidence

`evidence_id`, `analysis_run_id`, `module_id`, `module_version`, `family`, `instrument_id`, `timeframe`,
`observed_at`, `available_at`, `direction`, `strength` (۰..۱), `confidence_raw` (۰..۱، **نه احتمال**),
`price_zone`, `invalidation`, `expiry`, `parameters_hash`, `source_refs`, `explanation`.

`confidence_raw` هرگز به‌عنوان «درصد موفقیت» نمایش داده نمی‌شود.

## ۴. Scenario

`scenario_id`, `status` (DRAFT/WATCH/ARMED/TRIGGERED/INVALIDATED/EXPIRED/REJECTED), `direction`,
`entry_condition`, `entry_zone`, `invalidation_condition`, `stop_logic`, `target_logic`, `expiry_at`,
`evidence_ids`, `risk_decision_id`, `decision_explanation`, `rules_version`, `config_hash`.

گذار وضعیت فقط با `ScenarioTransition` ثبت‌شده (actor، دلیل، زمان، data_ref) مجاز است.

## ۵. RiskDecision

`decision_id`, `scenario_id`, `account_snapshot_id`, `approved`, `risk_amount`, `risk_currency`,
`position_size`, `entry_price`, `stop_loss`, `take_profit`, `checks_passed/failed`, `policy_version`,
`reason_code`, `reason_detail`, `valid_until`, `inputs_hash`.

## ۶. قواعد کیفیت داده

| کنترل | قاعده | اقدام |
|---|---|---|
| توالی | زمان تکراری/نامعتبر | قرنطینه + گزارش |
| OHLC | ناسازگاری | INVALID |
| مقادیر منفی | قیمت/اسپرد/حجم | قرنطینه |
| شکاف | مقایسه با تقویم سشن | WARN (پرکردن کورکورانه ممنوع) |
| Freshness | کهنگی نسب به آخرین بازار باز | FAIL و NO TRADE |
| واگرایی منابع | اختلاف > آستانه پیپ | WARN/SUSPECT |
| اصلاح تاریخچه | محتوای متفاوت با کلید یکسان | revision جدید + log |

آستانه‌ها در `DataQualitySettings` و بخش `data_quality` پیکربندی، نسخه‌دار و بخشی از `config_hash` هستند.

## ۷. ذخیره‌سازی و Lineage

- داده خام در `raw_payloads` فقط‌افزودنی است (Trigger ضد UPDATE/DELETE).
- هر ورود، هش محتوا و مسیر فایل را ثبت می‌کند.
- `candidate` اصلاح‌شده با `source_revision` و `candle_revision_log` قابل ردیابی است.
- Snapshot هر تحلیل بر مبنای محتوای کندل‌های مصرف‌شده ساخته می‌شود.

## ۸. Data Trust Score (DTS)

مبنا: سند تکمیلی ۱.۱ §۴-۲. هر تحلیل پیش از انتشار، `TrustBreakdown` را در `analysis_meta.data_trust` ثبت می‌کند:

| فیلد | معنا |
|---|---|
| `freshness` | تازگی آخرین داده نسبت به زمان تصمیم (بر حسب کندل) |
| `completeness` | نسبت کندل‌های موجود به کندل‌های مورد انتظار تقویم |
| `consistency` | ناسازگاری OHLC، تکرار، شکاف و پرش اسپرد |
| `schema_validity` | فیلدهای اجباری، ترتیب زمانی، `is_closed` و `quality_status` |
| `source_reliability` | اتکای منبع/نسخه (قابل تنظیم؛ پیش‌فرض ۱) |
| `score` | میانگین وزنی پنج مؤلفه در بازه ۰..۱ |
| `status` | `TRUSTED` / `DEGRADED` / `UNTRUSTED` |
| `reasons` | دلایل فارسی کاهش امتیاز |

قاعده: `score < trust.min_score` (پیش‌فرض ۰٫۶۰) ⇒ `NO_TRADE` با کد `DATA_UNTRUSTED`. خطای محاسبه نیز Fail-Safe است.

## ۹. Evidence Graph

`analysis_meta.evidence_graph`:

- `graph_id`، `nodes` (هر گره: `evidence_id`، خانواده، جهت، قدرت، اتکا، زمان) و `edges`.
- یال `redundant` بین شواهد هم‌خانواده/نزدیک زمانی؛ شواهد تکراری در تجمیع وزن کامل نمی‌گیرند.
- `direction_summary` تعداد شواهد LONG/SHORT/NEUTRAL.

## ۱۰. Decision Provenance Store

جدول فقط‌افزودنی `decision_provenance`:

`record_id`, `analysis_run_id`, `decision_id`, `scenario_id`, `tenant_id`, `decision_status`,
`no_trade_reason`, `data_cutoff`, `data_quality_status`, `regime`, `evidence_graph_ref`,
`uncertainty_factors` (JSON), `risk_gate_result`, `config_hash`, `code_version`,
`model_versions` (JSON), `reason_codes` (JSON), `human_override`, `prev_hash`, `record_hash`, `created_at`.

`record_hash = sha256(prev_hash + محتوای رکورد)` است. `verify_chain` اولین رکورد شکسته را گزارش می‌کند.

## ۱۱. دفتر تصمیم و چالش

- `decision_journal`: `entry_id`, `tenant_id`, `analysis_run_id`, `scenario_id`, `kind`, `severity`, `body`, `actor`, `created_at`, `payload`.
- `scenario_challenges`: `challenge_id`, `scenario_id`, `tenant_id`, `thesis`, `actor`, `status`, `created_at`, `payload`.
- `model_drift`: `model_id`, `drift_type`, `value`, `threshold`, `detected_at`, `actor`, `payload`.

هر سه فقط‌افزودنی‌اند و در ممیزی با اکشن‌های `DECISION_JOURNAL_RECORDED` و `SCENARIO_CHALLENGED` ثبت می‌شوند.
