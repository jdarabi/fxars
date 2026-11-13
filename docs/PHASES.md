# نقشه راه و دروازه‌های فاز

مبنا: بخش «۱۷. نقشه راه» سند جامع `FX-ARS-SRS-ARCH-002`. هر فاز خروجی قابل استفاده و معیار پذیرش مستقل دارد.

| فاز | دامنه | تحویل‌دادنی و دروازه عبور | وضعیت |
|---|---|---|---|
| ۰. تحلیل | تثبیت SRS، نماد/TF، داده، ریسک و معیار | تصویب دامنه و معیارهای پذیرش | ✅ تصویب‌شده |
| ۱. داده | Adapter، ingestion، validation، storage | کیفیت داده و بازتولید معتبر | ✅ کامل و اعتبارسنجی‌شده روی داده واقعی MT5 |
| ۲. تحلیل پایه | ساختار، تکنیکال، پرایس‌اکشن، نوسان و سناریو | آزمون واحد و تطبیق نمونه | ✅ کامل |
| ۳. آزمایشگاه | بک‌تست، هزینه، گزارش و walk-forward | عدم leakage و هزینه واقع‌گرایانه | ✅ کامل (PBO/DSR/Monte Carlo) |
| ۴. ریسک | Risk Gate، هشدار و audit | آزمون سناریوهای بحرانی | ✅ کامل (fail-closed) |
| ۵. هوشمندی | رژیم بازار، ML، کالیبراسیون و purged CV | بهبود OOS نسبت به baseline | ✅ کامل و آزمون‌شده |
| ۶. دمو | سفارش آزمایشی، state machine، idempotency، reconciliation، forward test | موفقیت forward test و تطبیق | ✅ کامل (PaperBroker + MT5 demo + Forward Harness) |
| ۷. تجاری | چندمستاجری، اشتراک، پشتیبانی، امنیت | ممیزی امنیت و حقوق داده | ✅ کامل (`security-audit`) |

## دروازه‌های تصمیم (Gate A..G)

- **A — تصویب طراحی:** دامنه، نماد پایلوت، منبع داده، قراردادها، Acceptance. ✅
- **B — آمادگی داده:** کیفیت، تازگی، Lineage، بازتولید. ✅
- **C — آمادگی تحلیل:** تعریف/نسخه/آزمون الگوریتم‌ها. ✅
- **D — آمادگی پژوهش:** پروتکل OOS، هزینه‌ها، گزارش بازتولیدپذیر. ✅
- **E — آمادگی Demo:** State machine، Idempotency، Reconciliation، Fault test. ✅
- **F — آمادگی اجرای واقعی:** ریسک، امنیت، Forward test، Kill Switch، تأیید رسمی. 🟡 (فنی کامل؛ Forward Test مستند PASS در `reports/forward-test-20261111.md`؛ تأیید رسمی اپراتور لازم است)
- **G — تجاری‌سازی:** حقوق داده، Tenant isolation، پشتیبانی، انطباق. ✅ (پیاده‌سازی و ممیزی خودکار؛ شواهد JSON: `reports/phase7-20261111.json`)

## قواعد فاز

1. قابلیت فاز بعد در فاز قبل «ناقص» فعال نمی‌شود؛ مدل داده می‌تواند آماده باشد.
2. هر تغییر مؤثر بر منطق معاملاتی/ریسک/داده نیازمند شناسه تغییر، نسخه و آزمون رگرسیون است.
3. فعال‌سازی هر فاز فقط با مدرک مستند عبور از دروازه مربوطه.

## وضعیت فعلی

- فاز پیش‌فرض: `READ_ONLY`؛ `ExecutionService` در این فاز هر تلاش ساخت OrderIntent را با `PHASE_VIOLATION` رد و Audit می‌کند.
- چندمستاجری سطری: `tenant_id` در کاربران، تحلیل‌ها، سناریوها، تصمیم‌های ریسک و سفارش‌ها؛ دسترسی به مستاجر دیگر 404 و مستاجر غیرفعال 403 می‌شود.
- اشتراک: پلن‌های `basic` / `pro` / `enterprise` با سهمیه کاربر، تحلیل روزانه و سناریوی فعال؛ سقف‌گذاری در مرز سرویس با `QUOTA_EXCEEDED` (HTTP 429).
- حقوق داده: خروجی JSON مستاجر بدون هش رمز/توکن/secret و گزارش سیاست نگهداری؛ حذف دسته‌ای فقط با تأیید صریح اپراتور.
- ممیزی امنیت: `python -m fxars.cli.main security-audit` (MFA، TTL نشست، نرخ، اسرار، ستون‌های tenant، زنجیره ممیزی، نشت اسرار، حقوق داده).
- KMS: لایهٔ `fxars/security/kms.py` کلید TOTP و امضای لنگر ممیزی را مشتق می‌کند؛ `kms_provider=env` کلید را از `FXARS_KMS_MASTER_KEY` می‌گیرد (چرخش با `FXARS_KMS_MASTER_KEY_PREVIOUS`). لنگر خارجی: `audit-anchor --out` و `audit-verify-anchor --file`.
- بستن معاملات: `reconcile-closes`/`reconcile` سفارش‌های FILLED را با هیستوری بروکر تطبیق و با سود/زیان واقعی `CLOSED` می‌کند؛ در نبود هیستوری، `RECONCILIATION_REQUIRED` ثبت می‌شود. گزارش انتساب عملکرد: `attribution` یا `GET /api/v1/trading/attribution`.
- پیکربندی Fail-Fast: `Settings.from_dict/load` قواعد سازگاری ریسک/تحلیل/بک‌تست را پیش از اجرا بررسی می‌کند؛ درایو `drawdown_warn < drawdown_stop`، `risk_per_trade ≤ hard_cap` و سقف `scenario_expiry_bars` تضمین می‌شوند.
- اتصال MT5 مشترک با شمارش مرجع (`fxars/live/mt5_connection.py`) و کش منفی نماد؛ مرز شمارش روزانه `trading_day_start` (۱۷:۰۰ نیویورک) است.
- تغییر فاز در زمان اجرا: `Platform.apply_phase` هم‌زمان `settings`، `phase_settings`، `ExecutionService`، `StrategyExecutionService`، `CloseReconciliationService` و بروکر را به‌روز می‌کند و فایل `config/phase.json` را می‌نویسد؛ `POST /api/v1/phase` بدون ری‌استارت اعمال می‌شود. daemon زنده در هر چرخه با `reload_phase` فایل فاز را دوباره می‌خواند، پس سوئیچ داشبورد روی پروسهٔ معاملات هم اثر می‌گذارد.
- تنظیمات هوشمند معاملات: `fxars/config/trading_defaults.py` بر اساس سرمایه، پروفایل ریسک/لات/پوزیشن/تایم‌فریم و «پله‌های حجم» را پیشنهاد می‌دهد؛ `GET/POST /api/v1/trading/settings` پیشنهاد را نشان و مقادیر ویرایش‌شده را پس از اعتبارسنجی با سقف سیاست ریسک ذخیره و فوری اعمال می‌کند. ریسک هر معاملهٔ `automated_limited` در محاسبهٔ حجم مؤثر است (با سقف `hard_cap_risk_per_trade`).
- تعداد آزمون‌ها و آخرین نتیجه در `docs/IMPLEMENTATION_REPORT.md` ثبت می‌شود.

## سند تکمیلی ۱.۱ (ارتقای تصمیم و حاکمیت)

پیاده‌سازی تکمیلی روی همان فازها اعمال شده و فاز جدیدی باز نکرده است:

| قابلیت | ماژول | وضعیت |
|---|---|---|
| Data Trust Score + `DATA_UNTRUSTED` | `fxars/data/trust.py` | ✅ |
| Evidence Graph + امتیاز ترکیبی | `fxars/decision/evidence_graph.py`, `score.py` | ✅ |
| بودجه عدم‌قطعیت | `fxars/decision/uncertainty.py` | ✅ |
| Decision Provenance | `fxars/governance/provenance.py` | ✅ |
| Policy Registry / Model Registry | `fxars/governance/policy.py`, `models.py` | ✅ |
| قفل ریسک + کنترل زیان هفتگی/سشن | `fxars/risk/lock_lifecycle.py`, `gate.py`, `service.py` | ✅ |
| Kill Switch سه‌سطحی | `fxars/risk/killswitch.py` | ✅ |
| ژورنال/بازپخش/پیش‌مرگ/نقشه حرارتی/چالش | `fxars/decision/intelligence.py` | ✅ |
| دروازه پذیرش پژوهش | `fxars/research/acceptance.py` + `research-gate` | ✅ |
| تب «هوشمندی تصمیم» | `fxars/ui/dashboard.py` | ✅ |
| مستند ردیابی | `docs/SUPPLEMENT_V1_1.md`, `docs/MVP.md` | ✅ |

نکته: فعال‌سازی فاز معاملاتی (`ASSISTED`/`AUTOMATED_LIMITED`) همچنان به دروازه F و تأیید رسمی ریسک وابسته است؛ قابلیت‌های تکمیلی این الزام را حذف نمی‌کنند.

## گام بعدی

- فعال‌سازی فاز اجرای محدود (`ASSISTED`/`AUTOMATED_LIMITED`) فقط پس از تأیید رسمی ریسک؛ شاهد فنی دروازه F (Forward Test روی کپی داده واقعی، ۲۵۶ گام، PASS، بدون نقض look-ahead) در `reports/forward-test-20261111.md` ثبت شده است.
- انتقال پایگاه داده به PostgreSQL و Rate Limit مشترک برای استقرار چندنمونه‌ای (زیرساخت آماده است).
- آداپتور KMS ابری/HSM و ایزولاسیون کلید به‌ازای مستاجر؛ نگهداری لنگر ممیزی در WORM/offsite برای امضای نامتقارن.
