# Changelog — FX-ARS

## [v1.11.0] — 2026-11-12

### Added (فیلتر روند تایم‌فریم بالاتر برای استراتژی‌های M5)
- **قانون:** سیگنال‌های `EMA20/FullBody` و `H&S/Reversal` فقط وقتی پذیرفته می‌شوند که هم‌جهت با روند H1 باشند. جهت روند = موقعیت آخرین کندل **بستهٔ** H1 نسبت به EMA50 آن؛ خرید فقط در روند صعودی و فروش فقط در روند نزولی.
- **بدون نگاه به آینده:** برای هر کندل M5 فقط کندل‌های H1 با `close_time <= open_time` کندل ورودی استفاده می‌شوند؛ تست واحد مرز زمانی را پوشش می‌دهد.
- **Fail-closed:** اگر روند H1 در دسترس یا مشخص نباشد (کندل بستهٔ کافی برای EMA50 وجود نداشته باشد)، ورود مسدود می‌شود؛ در API برای تایم‌فریم M5 کندل‌های H1 به‌صورت خودکار و از همان اتصال MT5 دریافت می‌شوند و خطای دریافت H1 به‌جای صدور سیگنال بدون فیلتر، خطا برمی‌گرداند.
- **بک‌تست هم‌سو با اجرا:** امتیازدهی دو استراتژی دستی در `select_best_strategy` نیز با فیلتر محاسبه می‌شود، پس مقایسهٔ استراتژی‌ها با رفتار واقعی هم‌خوان است.
- **پاسخ API:** فیلد جدید `trend_filter` شامل `timeframe`، `applied` و `direction` (`UP`/`DOWN`/`null`)؛ اگر سیگنال خام وجود داشته ولی به‌خاطر ناهم‌سویی رد شده باشد، `reason` همین را توضیح می‌دهد.
- **داشبورد:** نمایش جهت روند H1 در نتیجهٔ تحلیل و به‌روزرسانی راهنمای انتخاب استراتژی دستی.
- **شاهد داده واقعی (EURUSD، ۲۰۰۰ کندل M5):** برای `H&S/Reversal` تعداد معامله ۹۷ → ۶۵، نرخ برد ۶۲٪ → ۷۴٪، ضریب سود ۳٫۰۲ → ۶٫۴۱ و حداکثر افت ۶٫۷۹٪ → ۳٫۹۸٪؛ برای `EMA20/FullBody` در این بازه سیگنالی وجود نداشت.

### Tests
- ۹ آزمون جدید در `tests/test_user_strategies.py`: هم‌ترازی زمانی H1، روند صعودی/نزولی، مسدودسازی سیگنال خلاف روند، حالت نامشخص (fail-closed)، گزارش `trend_filter`، و انتخاب فقط برای M5 در API.
- ۲ آزمون رگرسیون UI برای نمایش جهت روند H1 و راهنمای انتخاب استراتژی دستی در `tests/test_dashboard_trading_settings_ui.py`.
- اجرای کامل: **781 آزمون، OK (7 skip)**.

---

## [v1.10.0] — 2026-11-12

### Changed (تنظیمات هوشمند معاملات: هشدار به‌جای سقف اجباری)
- **رفع محدودیت انتخاب:** فهرست تایم‌فریم‌ها در تب «💼 معاملات → ⚙️ تنظیمات هوشمند» کامل شد (`M5`, `M15`, `H1`, `H4`, `D1`) و فهرست نمادها دیگر به ده نماد پیشنهادی محدود نمی‌شود؛ همهٔ نمادهای ثبت‌شده در پایگاه داده (از جمله `BTCUSD`، `ETHUSD`، `XAGUSD`) قابل انتخاب‌اند.
- **اعتبارسنجی دو سطحی:** `validate_automated_settings_soft` خطاهای ساختاری (صفر/منفی، تایم‌فریم ناشناخته، نماد بدون مشخصات) را جدا از هشدارهای عبور از سیاست برمی‌گرداند. مقادیر معتبرِ خارج از سقف سیاست (ریسک، زیان روزانه، افت سرمایه، تعداد پوزیشن/معامله، اسپرد، حجم بیش از سقف نماد، نماد خارج از فهرست پیشنهادی) فقط هشدار می‌گیرند.
- **تأیید صریح پیش از ذخیره:** `POST /api/v1/trading/settings` در صورت وجود هشدار، `200` با `requires_confirmation: true` و فهرست `warnings` برمی‌گرداند و چیزی روی دیسک نمی‌نویسد؛ فقط تکرار درخواست با `confirm_warnings: true` ذخیره و اعمال می‌کند. داشبورد هشدارها را در `confirm()` نشان می‌دهد و در صورت انصراف، پیام «ذخیره لغو شد» ثبت می‌کند.
- **Fail-safe حفظ شد:** موتور ریسک (`RiskService`/`RiskGate`) مستقل از این تنظیمات، سقف‌های سخت سیاست را در زمان ارزیابی و ارسال سفارش اعمال می‌کند.

### Fixed
- **خطای نگارشی JS در داشبورد:** رشته‌های `join("\n")` و پیام `confirm` در منبع `DASHBOARD_HTML` به‌صورت `\\n` اصلاح شدند؛ پیش‌تر به‌خاطر تفسیر escape در رشتهٔ غیر-raw پایتون، شکست خط واقعی داخل رشته ایجاد و کل اسکریپت داشبورد از کار می‌افتاد.

### Tests
- ۵ آزمون UI جدید در `tests/test_dashboard_trading_settings_ui.py` (تایم‌فریم‌های کامل، فهرست نماد از سرویس، جریان تأیید و `confirm_warnings`، متن راهنما).
- ۶ آزمون جدید/بازنویسی‌شده در `tests/test_trading_defaults.py` برای حالت نرم، هشدارها و جریان تأیید API.
- اجرای کامل: **770 آزمون، OK (7 skip)** — جزئیات در `docs/IMPLEMENTATION_REPORT.md`.

---

## [v1.9.1] — 2026-11-12

### Fixed (Kill Switch قابل بازگشت از داشبورد)
- **باگ:** کارت «عملیات» فقط دکمهٔ «فعال» داشت و هر کلیک دوباره فعال می‌کرد؛ بنابراین پس از فعال‌شدن Kill Switch، معاملات قفل می‌ماند و از داشبورد راه غیرفعال‌سازی پیدا نمی‌شد. Audit نشان داد همهٔ رخدادها `activated` بودند و هیچ `deactivated` ثبت نشده بود.
- **اصلاح:** کارت عملیات به کلید دوطرفه تبدیل شد (فعال‌سازی/غیرفعال‌سازی) با نمایش وضعیت و دلیل جاری، تأیید پیش از غیرفعال‌سازی، و هم‌گام‌سازی نشان‌گر هدر. وضعیت Kill Switch در تب «معاملات» هم نمایش داده می‌شود.
- **آزمون:** ۱ آزمون HTTP برای چرخهٔ فعال/غیرفعال و به‌روزرسانی `meta` در `tests/test_security.py` و ۳ آزمون رگرسیون UI در `tests/test_dashboard_killswitch_ui.py`.

### Tests
- اجرای کامل: **760 آزمون، OK (7 skip)** — جزئیات در `docs/IMPLEMENTATION_REPORT.md`.

---

## [v1.9.0] — 2026-11-12

### Added (استراتژی‌های دستی کاربر — M5)
- **استراتژی «EMA20 + کندل فول‌بادی»:** کندل M5 بدون سایه (بدنه = دامنه) با بدنه ۱۰ تا ۲۰ پیپ که کاملاً بالای EMA20 و سبز باشد ⇒ خرید؛ کاملاً زیر EMA20 و قرمز ⇒ فروش. حد ضرر ۲ پیپ آن‌سوی کندل و حد سود دو برابر بدنه.
- **استراتژی «سر و شانه بازگشتی»:** الگوی شانه-سر-شانه بر پایه سوئینگ‌های تأییدشده؛ در حالت معکوس شانه راست بالاتر از شانه چپ و در حالت معمولی پایین‌تر از آن. تأیید با کندل سبز بالای EMA20 (خرید) یا قرمز زیر EMA20 (فروش)؛ حد ضرر ۲ پیپ آن‌سوی شانه چپ و حد سود ۲۰ پیپ (متقارن برای فروش).
- **انتخاب دستی استراتژی:** فهرست استراتژی‌ها در پاسخ تحلیل (`available`) و پارامتر `strategy` در `POST /api/v1/strategy/analyze`، `/strategy/trade` و `/strategy/trade_multi`؛ انتخاب خالی یعنی خودکار (بهترین امتیاز). استراتژی‌های کاربر فقط روی `M5` پذیرفته می‌شوند.
- **داشبورد:** انتخابگر استراتژی با ذخیره انتخاب در `localStorage`، قفل خودکار تایم‌فریم روی M5 و نمایش استراتژی انتخاب‌شده در نتیجه تحلیل و پیام تأیید ارسال سفارش.
- **مجوز فاز:** `automated_limited.timeframes` شامل `M5` شد تا سفارش‌های این استراتژی‌ها از دروازه فاز عبور کنند.

### Tests
- ۱۹ آزمون جدید در `tests/test_user_strategies.py`: قوانین فول‌بادی (سایه، بازه بدنه، جهت، SL/TP)، الگوی سر و شانه و ترتیب شانه‌ها، تریگر EMA، انتخاب دستی، و اعتبارسنجی API.
- اجرای کامل: **756 آزمون، OK (7 skip)** — جزئیات در `docs/IMPLEMENTATION_REPORT.md`.

---

## [v1.8.0] — 2026-11-12

### Added (سند تکمیلی ۱.۱ — تصمیم، ریسک و حاکمیت)
- **Data Trust Score (DTS):** پنج مؤلفه تازگی/کامل‌بودن/سازگاری/schema/اتکای منبع با میانگین وزنی؛ `DTS < 0.60` ⇒ `NO_TRADE/DATA_UNTRUSTED`. خروجی در `analysis_meta.data_trust`.
- **Evidence Graph و امتیاز ترکیبی:** گره/یال شواهد، تشخیص تکرار، و `S = Σw·E·R·F − P_conflict` با سهم هر خانواده در `analysis_meta`.
- **بودجه عدم‌قطعیت:** `U = αU_data + βU_model + γU_regime + δU_conflict + εU_execution`؛ عبور از ۰٫۶۰ ⇒ `NO_TRADE/UNCERTAINTY_TOO_HIGH`.
- **Decision Provenance:** زنجیره هش فقط‌افزودنی `decision_provenance`؛ هر تحلیل در همان تراکنش ثبت و با `GET /api/v1/governance/provenance/{run_id}` قابل بررسی است.
- **Policy Registry و Model Registry:** نسخه‌دارسازی سیاست، فعال‌سازی تک‌نسخه، Model Card، Tier 0–3، ممنوعیت Tier 3 در MVP، تأیید مستقل Tier 2، Shadow/Canary و ثبت Drift.
- **قفل ریسک:** چرخه `NORMAL/WARNING/LOCKED_DAILY/LOCKED_WEEKLY/KILL_SWITCH/MANUAL_REVIEW`؛ آزادسازی فقط با دلیل و نقش مجاز؛ نمایش تاریخچه در API/داشبورد.
- **Kill Switch سه‌سطحی:** `SYSTEM`/`MODULE`/`ACCOUNT` با `target` و بررسی Fail-Safe همه سطوح.
- **کنترل‌های جدید دروازه ریسک:** `risk_lock_clear`، `weekly_loss_within_limit` (۳× سقف روزانه) و `market_open` با grace؛ زیان هفتگی از `closed_trades` محاسبه می‌شود.
- **هوشمندی تصمیم:** Decision Journal، Counterfactual Replay، Pre-mortem، Scenario Heatmap و Challenge Mode با ذخیره‌سازی و Audit.
- **دروازه پذیرش پژوهش:** OOS_SAMPLE، PROFIT_FACTOR، MAX_DRAWDOWN، SHARPE، CALMAR، ECE، TRAIN_TEST_GAP، COSTS_MODELED و شش ضدالگو؛ API و `research-gate --strict`.
- **API:** ۱۴ مسیر جدید در `/api/v1/intelligence/*` و `/api/v1/governance/*` و `/api/v1/risk/lock` با مجوز و tenant.
- **داشبورد:** تب «هوشمندی تصمیم» شامل قفل ریسک، Kill Switch سطح‌دار، نقشه حرارتی، ژورنال، پیش‌مرگ/بازپخش، منشأ و چالش/سیاست/مدل.
- **مستندات:** `docs/SUPPLEMENT_V1_1.md` (ماتریس ردیابی)، `docs/MVP.md`، به‌روزرسانی API/ARCHITECTURE/DATA_CONTRACTS/RISK_POLICY/VALIDATION_PROTOCOL/ACCEPTANCE/PHASES/README.

### Fixed
- **Kill Switch سطح‌دار:** `all_status` ستون ناموجود `payload` را می‌خواند و با حالت غیرفعال خطا می‌داد؛ اکنون فقط `key` خوانده می‌شود.
- **پایداری قفل ریسک:** `RiskService` ماشین قفل را با زیان روزانه/هفتگی و افت سرمایه به‌روز می‌کند؛ پیش از این فقط از API دستی تغییر می‌کرد.
- **سقف حجم فاز:** اگر حجم تأییدشده از `max_volume_per_order` بیشتر باشد، اکنون به سقف کاهش می‌یابد و ریسک/حجم تصمیم هم‌زمان اصلاح می‌شود؛ پیش از این کل سفارش با `VOLUME_x>cap` رد می‌شد. سقف کوچک‌تر از حداقل لات همچنان Fail-Closed است.
- **وضعیت سناریو در اجرا:** `ExecutionService` اکنون تنظیم `require_triggered_scenario` فاز `AUTOMATED_LIMITED` را رعایت می‌کند؛ پیش از این daemon ورود ARMED را مجاز می‌دانست اما ساخت سفارش آن را رد می‌کرد.
- **هم‌راستایی زمان‌بندی دمو:** `config/phase.json` و `config/live.json` به `M15` محدود شدند تا در حساب ۱۰۰ دلاری، سیگنال‌های H1 با استاپ بزرگ (۸۴ پیپ) باعث حجم صفر نشوند.

### Changed
- نسخه کد به `1.8.0` و نسخه پیش‌فرض سیاست ریسک به `risk_policy_v1.3` ارتقا یافت؛ `inputs_hash` تصمیم ریسک شامل `weekly_loss_fraction` و `risk_lock_active` است.
- مهاجرت `supplement_governance` (نسخه ۳) برای SQLite؛ schema اصلی نیز جداول جدید را به‌صورت idempotent می‌سازد.

### Tests
- ۷۳ آزمون جدید: `tests/test_decision_policy.py` (۱۹)، `tests/test_governance.py` (۱۷)، `tests/test_risk_lock.py` (۱۷)، `tests/test_intelligence.py` (۱۲)، `tests/test_acceptance_gates.py` (۸).
- ۵ آزمون جدید در `tests/test_volume_cap.py` برای کلمپ حجم، مقیاس ریسک، سقف زیر حداقل لات و مجازبودن ARMED در تنظیم فاز.
- اجرای کامل: **737 آزمون، OK (7 skip)** — جزئیات در `docs/IMPLEMENTATION_REPORT.md`.

---

## [v1.7.3] — 2026-11-12

### Added
- **تنظیمات هوشمند معاملات در داشبورد:** تایم‌فریم، حداکثر لات، تعداد پوزیشن، معاملات روزانه، ریسک/زیان روزانه، افت سرمایه، اسپرد و نمادها از روی سرمایه حساب پیشنهاد می‌شوند (`fxars/config/trading_defaults.py`) اما همه قبل از ذخیره قابل ویرایش‌اند. شش پروفایل سرمایه (micro/small/starter/standard/growth/pro) و «پله‌های حجم» برای فواصل حد ضرر ۱۰ تا ۱۲۰ پیپ نمایش داده می‌شود.
- **API تنظیمات:** `GET /api/v1/trading/settings?equity=N` (پیشنهاد + سقف سیاست + سرمایه مبنا) و `POST /api/v1/trading/settings` (اعتبارسنجی، ذخیره و اعمال فوری). تنظیمات با `audit` نوع `TRADING_SETTINGS_CHANGED` ثبت می‌شوند.
- **اعمال در زمان اجرا:** `Platform.apply_trading_settings` فایل `config/phase.json` را می‌نویسد و سرویس استراتژی را هم‌گام می‌کند؛ daemon با `reload_phase` هر تغییر تنظیمات (نه فقط mode/enabled) را در چرخه بعد می‌گیرد.

### Changed
- **ریسک هر معامله فاز خودکار واقعاً اثر می‌گذارد:** پیش‌تر `automated_limited.risk_per_trade` فقط ذخیره می‌شد؛ اکنون `RiskService` آن را به‌عنوان ریسک مؤثر (با سقف `hard_cap_risk_per_trade`) در محاسبه حجم استفاده می‌کند.
- **اعتبارسنجی سخت:** ریسک/زیان روزانه/پوزیشن/معاملات روزانه/اسپرد و نمادها/تایم‌فریم‌ها پیش از ذخیره با سیاست ریسک بررسی می‌شوند؛ مقدار خارج از سقف با پیام فارسی رد می‌شود و فایل دست‌نخورده می‌ماند.

### Tests
- `tests/test_trading_defaults.py` (۱۵): پروفایل‌های سرمایه، سقف‌گذاری سیاست، پله‌ها، اعتبارسنجی، coercion، اعمال API و سقف ریسک فاز.
- `tests/test_live_daemon.py` (+۱): reload تنظیمات معاملات بدون تغییر فاز.

---

## [v1.7.2] — 2026-11-11

### Fixed (بازخورد کاربر)
- **تغییر فاز بدون ری‌استارت:** `POST /api/v1/phase` پیش‌تر فقط `config/phase.json` را می‌نوشت؛ `settings`، سرویس‌ها و بروکر تا ری‌استارت روی فاز قبلی می‌ماندند و UI پس از `loadAll` به فاز قبلی برمی‌گشت. اکنون `Platform.apply_phase` در همان اجرا `settings`/`phase_settings`، `ExecutionService`، `StrategyExecutionService`، `CloseReconciliationService` و بروکر را هم‌گام می‌کند (نگاشت `ADVISOR→READ_ONLY`)، بروکر قبلی را shutdown و فایل فاز را می‌نویسد. پاسخ API شامل `runtime_phase`، `execution_enabled` و `broker` است.
- **هم‌گام‌سازی daemon زنده:** daemon در هر چرخه با `reload_phase=True` (فعال در `fxars live`) فایل فاز را دوباره می‌خواند و تغییر داشبورد را روی پروسه معاملات اعمال می‌کند؛ پیش از این، سوئیچ فاز فقط روی پروسه API اثر داشت و daemon روی فاز شروع می‌ماند.
- **شفافیت رد ریسک با سرمایه ۱۰۰ دلار:** `reason_detail` حالا عدد واقعی را می‌گوید: برای `BELOW_MIN_LOT` حجم لازم، حداقل ریسک لازم برای min_lot و درصد سرمایه؛ برای `STOP_DISTANCE_INVALID` فاصله پیپ و سقف سیاست؛ برای `MAX_OPEN_TRADES` تعداد باز و سقف. علت واقعی توقف معاملات (ریسک 0.25٪ ⇒ حجم زیر min_lot؛ 5٪ به‌همراه سقف حد ضرر ۳۰ پیپ؛ پوزیشن باز) دیگر پشت پیام عمومی پنهان نمی‌ماند. سیاست ریسک به‌صورت خودکار شل نشد.

### Security
- **پاکسازی نسخه‌های پشتیبان/کش:** مقدار رمز دموی قدیمی در `.fix-backups/`، `.cleanup-backups/` و `.hypothesis/constants/` با `REDACTED_DEMO_PASSWORD` جایگزین شد (۴۸ فایل، ۱۰۹ رخداد). اسکن هش‌محور پس از پاکسازی هیچ رخدادی از مقادیر قدیمی را نشان نداد؛ یک فایل کش Hypothesis که با جایگزینی بایتی خراب شده بود حذف شد (کش بازتولیدشدنی). مقادیر رمز هرگز چاپ نشدند.

### Tests
- `tests/test_phase_runtime.py` (۷): اعمال فاز، نگاشت ADVISOR، ساخت بروکر PAPER، حذف بروکر در READ_ONLY، پایداری فایل و مسیر API.
- `tests/test_live_daemon.py` (+۳): reload فاز از دیسک، عدم تماس در حالت یکسان، خاموش‌بودن پیش‌فرض.
- `tests/test_risk.py` (+۳): پیام‌های مشخص `BELOW_MIN_LOT`، `STOP_DISTANCE_INVALID` و `MAX_OPEN_TRADES`.
- اجرای کامل: **643 آزمون، OK (7 skip)**.

---

## [v1.7.1] — 2026-11-11

### Added (بازبینی نقد — P3)
- **KMS:** لایهٔ `fxars/security/kms.py` با دو تأمین‌کنندهٔ `local` و `env`؛ کلید هر کاربرد با HMAC-SHA256 مشتق می‌شود، `FXARS_KMS_MASTER_KEY` (hex/base64، حداقل ۳۲ بایت) و کلید قبلی برای چرخش پشتیبانی می‌شوند، و `KeyMaterial` مقدار کلید را در repr افشا نمی‌کند.
- **SecretBox نسخه‌دار:** TOTP با `v2:<key_id>:<payload>` رمز می‌شود؛ متن‌های legacy با کلید قدیمی خوانده می‌شوند و چرخش کلید بدون از دست رفتن MFA ممکن است.
- **لنگر خارجی ممیزی:** `AuditAnchorSigner` + دستورهای `audit-anchor --out` و `audit-verify-anchor --file`؛ امضای HMAC-SHA256 سر زنجیره و بررسی تطابق `head`/`count` برای آشکارسازی بازسازی/کوتاه‌سازی زنجیره. ۱۸ آزمون در `tests/test_kms.py` و ۳ آزمون تنظیمات.

### Fixed (بازبینی نقد — P0)
- **اعتبارسنجی تنظیمات:** `Settings.from_dict/load` حالا قواعد سازگاری را Fail-Fast بررسی می‌کند: `risk_per_trade ≤ hard_cap_risk_per_trade`، ترتیب `drawdown_warn < drawdown_stop ≤ max_drawdown_hard_cap`، بازهٔ `max_currency_exposure`/`max_correlation_exposure`، `min_signal_strength ∈ [0,1]`، `scenario_expiry_bars ∈ [1,100]`، سقف ریسک بک‌تست ۲٪ و کسرهای OOS. پیکربندی متناقض دیگر بی‌صدا بالا نمی‌آید.
- **رفع drift پیکربندی فعال:** `drawdown_warn` از ۰.۲۰ به ۰.۰۵ (قبلاً از stop بزرگ‌تر بود و هشدار هرگز پیش از توقف فعال نمی‌شد)، `scenario_expiry_bars` از ۲۴۰ به ۸ مطابق سند، `backtest.initial_equity` از ۱۰۰ به ۱۰۰۰۰ و `backtest.risk_per_trade` از ۴٪ به ۰.۲۵٪.
- **انتخاب استراتژی:** شبیه‌سازی `_simulate_simple` از درصد قیمت به مضرب R تغییر کرد (`r = pnl/risk`، `equity *= 1 + r*0.01`)؛ بازده نمادهای مختلف با قیمت‌های متفاوت اکنون قابل‌مقایسه است.
- **Demo mode:** `FXARS_ENABLE_DEMO=1` در محیط غیر `dev` در startup خطا می‌دهد (لایهٔ دفاعی دوم علاوه بر محدودیت مسیرها به dev+localhost).

### Fixed (P1)
- **اتصال MT5 مشترک:** ماژول `fxars/live/mt5_connection.py` با شمارش مرجع؛ `MT5Feed`، `MT5Broker` و دانلودر هیستوری دیگر با `shutdown` یکدیگر اتصال سراسری را قطع نمی‌کنند.
- **کش منفی نماد:** نماد ناموجود ۶۰ ثانیه کش می‌شود و هر درخواست کل فهرست نمادهای بروکر را اسکن نمی‌کند.
- **مرز روز معاملاتی:** `TradingCalendar.trading_day_start` (۱۷:۰۰ نیویورک، DST-aware) جای نیمه‌شب UTC را در شمارش معاملات روزانه و سود/زیان روزانهٔ daemon، RiskService، StrategyService و API گرفت.
- **شفافیت ریسک در UI:** پنل ریسک اکنون `checks_failed`، `reason_detail` و حجم صفر (`POSITION_SIZE_INVALID`/زیر حداقل لات) را برجسته نشان می‌دهد؛ تحلیل استراتژی نیز سیگنال/دلیل/ورود-حدضرر-هدف را نمایش می‌دهد.
- **AC-05:** آزمون دیگر بی‌قید skip نمی‌شود؛ در READ_ONLY مسیر سفارش را رد می‌کند و فقط در فاز سفارش‌محور skip می‌شود.

### Changed (P2/P3)
- گزارش کالیبراسیون برای نمونهٔ کمتر از ۱۰۰، «نمونه کافی نیست» اعلام می‌کند و ECE را به‌تنهایی قابل استناد نمی‌داند.
- `print` مسیر سیگنال دستی با logger جایگزین شد.
- اسکریپت‌های خطرناک/موقت ریشه پروژه قرنطینه شدند: `_direct_trade.py` (دورزدن RiskGate) به `.fix-backups/quarantine-20261111/` و اسکریپت‌های عیب‌یابی به `scripts/debug/` با پایگاه صریح و بدون رمز هاردکد (`FXARS_DEMO_PASSWORD`).
- ۶۷ فایل `.bak` پراکنده و `test-output.txt` کهنه به `.fix-backups/archive-20261111/` منتقل شدند.
- **رمز دمو از کد حذف شد:** رمز ثابت `admin`/`analyst` از `fxars/ui/dashboard.py`، `scripts/launcher.py` و اسکریپت‌های `improve2` حذف شد؛ `bootstrap` در نبود متغیر محیطی رمز تصادفی می‌سازد و یک‌بار نمایش می‌دهد، و لانچر در صورت نیاز از `FXARS_ADMIN_PASSWORD`/`FXARS_ANALYST_PASSWORD` می‌خواند. ورود سریع UI فقط نام کاربری را پر می‌کند.
- README هشدار نتایج شبیه‌سازی‌شده را شفاف کرد (نتایج قدیمی با ریسک ۴٪ و غیرقابل بازتولید با پیکربندی فعلی)؛ SECURITY مسیر KMS و الزامات demo mode را مستند کرد.

### Tests
- آزمون‌های جدید: `test_config_validation` (۹)، `test_strategy_selector` (۳)، `test_mt5_connection` (۵)، `test_kms` (۱۸)، آزمون مرز روز معاملاتی و verdict کالیبراسیون.
- اجرای کامل: **630 آزمون، OK (7 skip)**.

---

## [v1.7.0] — 2026-11-11

### Added (بستن معاملات و انتساب عملکرد)
- **Broker close reconciliation:** `CloseReconciliationService` سفارش‌های `FILLED`/`PARTIALLY_FILLED` را با هیستوری بروکر مقایسه می‌کند؛ در صورت بسته‌شدن پوزیشن، گذار `FILLED → CLOSED` (و در صورت نیاز `PARTIALLY_FILLED → FILLED → CLOSED`) با ثبت `Transition`، Audit (`TRADE_CLOSED`) و Outbox (`execution.trade.closed`) انجام می‌شود. کلید یکتایی `intent_id` عملیات را idempotent می‌کند.
- **`ClosedTrade`:** موجودیت تغییرناپذیر با سود/زیان واقعی بروکر (`gross_profit` + `commission` + `swap`)، قیمت ورود/خروج، حجم، زمان باز/بسته، `risk_amount` و `r_multiple`، و ابعاد انتساب (نماد، جهت، تایم‌فریم، رژیم، استراتژی، سناریو، ماژول‌های شاهد).
- **Attribution:** `AttributionService` گزارش win rate، سود خالص/ناخالص، profit factor، expectancy، میانگین برد/باخت، مجموع و میانگین R و مدت نگهداری را به تفکیک هفت بعد محاسبه می‌کند؛ معامله‌های چندماژولی در هر ماژول شاهد شمرده می‌شوند.
- **API:** `POST /api/v1/trading/reconcile-closes` (مجوز `EXECUTION_ORDER`)، `GET /api/v1/trading/closed-trades` و `GET /api/v1/trading/attribution` (مجوز `REPORT_READ`).
- **CLI:** `reconcile` علاوه بر سفارش‌های UNKNOWN، بستن معاملات را اجرا می‌کند (`--no-closes` برای غیرفعال‌سازی)؛ فرمان جدید `attribution` با `--since/--until/--instrument/--dimension/--json`.
- **Storage:** جدول `closed_trades` (SQLite additive + مهاجرت `closed_trades` نسخه ۲؛ PostgreSQL نسخه ۵) با ایندکس‌های `(tenant_id, closed_at)` و `(instrument_id, closed_at)` و `UNIQUE(intent_id)`؛ `ClosedTradeRepository` مستاجرمحور؛ `CandleRepository.recent_until` برای بازسازی رژیم در لحظه بسته‌شدن.
- **Broker:** `MT5Broker.closed_position` از `history_deals_get`/`history_orders_get` پوزیشن مربوط به intent را با `position_id`، `order` یا تطبیق magic/نماد/حجم/زمان پیدا می‌کند و قیمت میانگین ورود/خروج، سود، کمیسیون و سوآپ را برمی‌گرداند.
- **Dashboard:** تب «📈 عملکرد» با کارت‌های سود خالص/نرخ برد/Profit Factor/Expectancy/میانگین R، جدول انتساب هفت‌بُعدی (قابل تغییر) و جدول معاملات بسته‌شده؛ داده‌ها با ورود به تب یا دکمه بروزرسانی از API خوانده می‌شوند.
- **Unresolved safety:** اگر بروکر هیچ پوزیشن باز منطبق و هیچ معامله بسته‌شده‌ای نداشته باشد (intent قدیمی‌تر از یک ساعت)، سفارش به‌جای بستن ساختگی به `RECONCILIATION_REQUIRED` منتقل و Audit می‌شود.

### Verification
- اجرای کامل: **589 آزمون، OK (8 skip)** شامل ۱۴ آزمون `tests/test_closed_trades.py` و ۴ آزمون هیستوری بسته‌شدن در `tests/test_mt5_broker.py`.
- اجرا روی پایگاه تولید (پس از پشتیبان‌گیری `data/backups/fxars_pre_close_reconcile_20261111T132417Z.db`): ۲۷ سفارش `FILLED` باقی‌مانده → ۱۳ مورد با سود/زیان واقعی `CLOSED` شد (۵ برد / ۸ باخت، سود خالص ۷.۴۲ دلار، profit factor 2.35، میانگین R ≈ 0.12) و ۱۴ مورد `RECONCILIATION_REQUIRED` شدند، چون هیستوری ترمینال MT5 فقط از 2026-11-09 07:50 به بعد موجود است. هیچ سفارش باز باقی نماند؛ ۱۳ رکورد `TRADE_CLOSED` در Audit و Outbox ثبت و زنجیره هش ممیزی (۱۹۶۴ رکورد) سالم تأیید شد.

---

## [v1.6.0] — 2026-11-11

### Added (Phase 7 — تجاری، اشتراک و امنیت)
- **Tenant isolation:** `tenant_id` در کاربران، تحلیل‌ها، سناریوها، تصمیم‌های ریسک و سفارش‌ها؛ دسترسی به مستاجر دیگر 404 و مستاجر غیرفعال 403 (`TENANT_INACTIVE`). شناسه تحلیل/سناریو برای مستاجر غیرپیش‌فرض شامل `tenant_id` است تا تصادم رخ ندهد.
- **Subscription plans:** کاتالوگ `basic`/`pro`/`enterprise` با `UNLIMITED=-1`، سقف کاربر/تحلیل روزانه/سناریوی فعال، `quota_overrides` در سطح مستاجر و خطای `QUOTA_EXCEEDED` (429) در مرز سرویس.
- **API:** `/api/v1/tenant`, `/api/v1/tenant/export`, `/api/v1/tenant/retention`, `/api/v1/tenants`, `/api/v1/tenants/{id}` و مسیرهای export/retention مدیر؛ مجوز جدید `tenant.admin`.
- **Data rights:** خروجی JSON مستاجر بدون هش رمز/TOTP/توکن/secret و گزارش سیاست نگهداری با شمارش واقعی.
- **Security audit:** فرمان `python -m fxars.cli.main security-audit` (و `--json`) برای دروازه «ممیزی امنیت و حقوق داده».
- **CLI:** `tenants list|create|set-plan`.
- **Storage:** ستون‌های `plan` و `quota_overrides` در `tenants` (SQLite additive + PostgreSQL migration v4)؛ متدهای شمارش/فهرست مستاجر‌محور در Repositoryها.
- **Tests:** `test_tenant_isolation`, `test_tenant_quota`, `test_tenant_rights` (۲۴ آزمون جدید) شامل جداسازی، سهمیه، خروجی داده و ممیزی امنیت/دستکاری زنجیره.

### Fixed
- **Live Monitor positions:** `GET /api/v1/trading/positions` دیگر با نبود بروکر یا خطای بروکر، پاسخ خالی/500 نمی‌دهد؛ از سفارش‌های FILLED/PARTIALLY_FILLED داخلی پوزیشن می‌سازد (میانگین ورود از Fill/BrokerOrder، قیمت جاری از آخرین کندل بسته و PnL با contract size). پاسخ شامل `source` (`broker`/`system`)، `broker`، `phase` و `errors` است.
- **Live Monitor UI:** تب «مانیتور لایو» بازنویسی شد؛ پوزیشن‌های باز اول نمایش داده می‌شوند (۹ ستون شامل وضعیت و زمان)، منبع/فاز/آخرین بروزرسانی و هشدار خطا شفاف است، پایش پس از تعویض تب ادامه می‌یابد و خطاها دیگر جدول را خراب نمی‌کنند.
- **Repositories:** `CandleRepository.latest_closed`، `OrderRepository.list_open_intents`، `latest_broker_order` و `list_fills` افزوده شد.
- **Benchmark isolation:** `scripts/benchmark_regime.py` به‌صورت پیش‌فرض روی داده دمو در حافظه اجرا می‌شود (گزینه `--db` برای پایگاه صریح)؛ پیش از این آزمون بنچمارک روی `data/fxars.db` تولیدی بک‌تست/Audit می‌نوشت. کل مجموعه پس از اصلاح دوباره روی تولید بدون نوشتن آزمون اجرا و بررسی شد.
- **Forward test warmup:** مقدار پیش‌فرض از ۲۰۰ به ۳۰۰ افزایش یافت تا از `min_bars=220` تحلیل بیشتر باشد و گام‌های ابتدایی با `INSUFFICIENT_DATA` هدر نروند (CLI و API).

### Tests
- `tests/test_live_positions.py` (۶ آزمون): fallback سیستم در READ_ONLY، حالت خالی، اولویت بروکر، افتادن به سیستم هنگام خطای بروکر، پوزیشن PARTIALLY_FILLED و جداسازی مستاجر. کل مجموعه: **571 آزمون، OK (8 skip)**.

---

## [v1.4.12] — 1405-08-12

### Added (Infrastructure)
- FIX-10-PG: real PostgreSQL backend (factory + schema + migrations + CLI)
- FIX-11-REDIS: Redis rate limit backend
- FIX-12-CLEANUP: idempotency cleanup job

---

## [v1.4.11] — 2026-11-03

### Fixed (P0 — Security & Data Correctness)
- **FIX-08 Rate Limit:** IP bucket before auth + user bucket after auth. Removed `_rate_key` prefix-based bypass.
- **FIX-03 Demo harden:** `FXARS_ENABLE_DEMO=1` required explicitly; production rejects weak/default `secret_key` (fail-fast).
- **FIX-04 SUSPECT/INVALID:** closed candle with `available_at < close_time` → INVALID (prevents look-ahead); only VALID enters analysis/backtest; `DataQualityRun.verdict=FAIL` → `NO TRADE/DATA_QUALITY_FAIL`.
- **FIX-09 Outbox:** handler-missing events are no longer lost (skip not publish); retry with attempts, last_error, dead_letter_at.
- **FIX-09 Idempotency:** atomic state machine (pending/completed/failed); replay returns stored response; parallel requests return 409; failed retries allowed with new body.

### Fixed (P1 — Research Validity)
- **FIX-06a Swap:** `bars × timeframe_minutes / 1440` (was `bars/24`, only correct for H1).
- **FIX-06b Gap Stop:** gap-aware exit at `open` when the bar opens beyond stop.
- **FIX-06c Fallback transparency:** `fallback_count` and `fallback_errors` in `stats`.

### Fixed (Discovered)
- `AnalysisService` did not receive `quality_runs` despite DQ gate requiring it (silent `AttributeError` → every analysis returned `NO_TRADE/DATA_QUALITY_FAIL`). Wired through `__init__` and `Platform`.
- `DataQualityRepository.list()` does not accept `timeframe` kwarg; DQ gate now calls `list(instrument_id=..., limit=10)` and filters in Python.
- `_with_idempotency` documented "inside domain transaction" but was not. Now atomic via state machine.
- Old tests (`test_pending_count_decreases`, `test_analysis_and_idempotent_replay`) aligned with new behavior (delta-based / handler-required).

### Changed (semantics)
- `no_trade_reason` priority: `NO_DATA` < `INSUFFICIENT_DATA` < `DATA_STALE` < `DATA_QUALITY_FAIL`.
- DQ gate only blocks on `verdict=FAIL`; access errors log + allow.
- Idempotency: `failed` allows retry with any body; `completed/pending` with different hash → 409.

---

تمام تغییرات قابل توجه در این فایل ثبت می‌شوند.

## [v1.4.10] — 2026-11-03

### Added
- **P4-3-ext**: Postgres schema translation
  - `fxars/storage/postgres_schema.sql` (TIMESTAMPTZ, JSONB, BIGSERIAL)
  - `fxars/storage/postgres_migrations.py` (idempotent upgrade runner)
  - 5 tests (3 always run, 2 skip without psycopg/DSN)

## [v1.4.9] — 2026-11-03

### Added
- **P6-5**: Paper Trading E2E with file-based database
  - Full pipeline: Analysis → Risk → Intent → Submit → Fill → Reconciliation
  - Persistence across close/reopen
  - 3 E2E tests

### Fixed
- `ExecutionService.submit`: honor broker's actual status (UNKNOWN, REJECTED)
- `state_machine`: ACKNOWLEDGED → UNKNOWN, UNKNOWN → terminal states

## [v1.4.8] — 2026-11-03

### Added
- **P3-5**: Regime filter benchmark suite
  - `scripts/benchmark_regime.py` (baseline vs filtered, regression guard)
  - CI integration (smoke job)
  - 1 smoke test

## [v1.4.7] — 2026-11-03

### Added
- **P5-4**: Metrics dashboard HTML page
  - `/metrics-dashboard` endpoint
  - Persian RTL page with uptime, counters, gauges, histograms
  - 6 tests

## [v1.4.6] — 2026-11-03

### Added
- **P4-3**: Postgres adapter skeleton
  - `PostgresDatabase` implementing `DatabaseProtocol`
  - SQL translation (? → %s)
  - 4 tests (2 pass without psycopg)

## [v1.4.4] — 2026-11-03

### Added
- **P6-3**: Reconciliation CLI
  - `python -m fxars reconcile`
  - `python -m fxars orders list [--status ...]`
  - `python -m fxars orders show <intent_id>`
- **P6-4**: `--allowed-regimes` shortcut for `backtest` command

## [v1.4.3] — 2026-11-03

### Added
- **P6-2**: Phase Guard E2E tests
  - `make_env(phase=...)` parameter
  - 6 tests (READ_ONLY blocks, PAPER allows full pipeline)

## [v1.4.2] — 2026-11-03

### Changed
- `docs/PHASES.md`: MVP-1 complete, MVP-2 in progress
- `README.md`: regime filter results (+144% net, +182% Sharpe)

## [v1.4.1] — 2026-11-03

### Added
- **P6-1**: PaperBroker faults + Reconciliation
  - Fault injection (reject, timeout, partial)
  - `ReconciliationService` for UNKNOWN orders
  - `OrderRepository.list_intents_by_status()`
  - 9 tests

## [v1.4.0] — 2026-11-02

### Added
- **P4-2**: Migration framework (up/down/history)
- Milestone: P0-P5 complete

## [v1.3.16] — 2026-11-02

### Added
- **P4-1**: Storage Protocol
  - `DatabaseProtocol` (runtime_checkable)
  - `InMemoryDatabase` for tests
  - 5 parity tests

## [v1.3.14] — 2026-11-02

### Added
- **P5-3**: Structured logging
  - Bearer/Basic/JWT/API-key redaction
  - Error JSONL file with rotation
  - 10 tests

## [v1.3.13] — 2026-11-02

### Changed
- `docs/ALGORITHMS.md`, `docs/DECISIONS.md`: regime filter documentation

## [v1.3.12] — 2026-11-02

### Added
- **P7**: GitHub Actions CI
  - Lint (ruff), typecheck (mypy), test matrix (Ubuntu+Windows, Py3.11+3.12)
  - Coverage, smoke with regime benchmark

## [v1.3.11] — 2026-11-02

### Added
- **P3-4-ext3**: `allowed_regimes` in `BacktestSettings`

## [v1.3.10] — 2026-11-02

### Added
- **P3-4-ext2**: Regime filter in backtest
  - `BacktestConfig.allowed_regimes`
  - **Result: +144% net profit, +182% Sharpe on demo**
- 6 tests

## [v1.3.9] — 2026-11-02

### Changed
- `report.py`: consolidated calibration + regime sections

## [v1.3.7] — 2026-11-02

### Added
- **P3-4**: Regime Detection
  - `fxars/research/regime.py`: 5 regimes (TRENDING_UP/DOWN, RANGING, HIGH_VOL, LOW_VOL)
  - `regime_breakdown()` for per-regime attribution
  - 13 tests

## [v1.3.6] — 2026-11-02

### Added
- **P3-1-ext**: ML pipeline
  - `fxars/research/ml_pipeline.py`: Triple Barrier + Purged K-Fold integration
  - 7 tests

## [v1.3.5] — 2026-11-02

### Added
- **P3-1**: Triple Barrier labeling
  - `fxars/research/labeling.py`
  - 12 tests

## [v1.3.4] — 2026-11-02

### Added
- **P3-2**: Purged K-Fold
  - `fxars/research/purged_cv.py`
  - `ResearchService.run_purged_cv()`
  - 14 tests

## [v1.3.3] — 2026-11-02

### Added
- **P3-3**: Calibration
  - `fxars/research/calibration.py`: Brier, LogLoss, ECE, Temperature Scaling
  - 21 tests

## [v1.3.2] — 2026-11-02

### Added
- **P5**: Observability
  - `/api/v1/metrics` (Prometheus)
  - `/api/v1/health/live`, `/api/v1/health/ready`
  - 10 tests

## [v1.3.1] — 2026-11-02

### Added
- **P0/P1**: 10 critical fixes
  - Bitemporal invariants (Candle, EconomicEvent)
  - Session revocation on password change
  - Killswitch re-enforcement in submit
  - Idempotent replay (no duplicate audit/outbox)
  - Primary-source correlations
  - Consecutive login failures
  - Bidirectional pagination

### Fixed
- `floor_to_timeframe`: zeros microsecond (property test)
- `_Handler`: drain oversized bodies before 413

### Tests
- 188 → 338 across P0-P5

---

## Summary by milestone

| Version | Focus | Tests |
|---|---|---|
| v1.3.1 | P0/P1: Critical fixes + hardening | 188 |
| v1.3.2 | P5: Observability | 257 |
| v1.3.4 | P3-2: Purged K-Fold | 271 |
| v1.3.5 | P3-1: Triple Barrier | 283 |
| v1.3.6 | P3-1-ext: ML Pipeline | 291 |
| v1.3.7 | P3-4: Regime Detection | 303 |
| v1.3.10 | P3-4-ext2: Regime Filter | 309 |
| v1.3.12 | P7: CI Pipeline | 309 |
| v1.3.14 | P5-3: Structured Logging | 319 |
| v1.3.16 | P4-1: Storage Protocol | 324 |
| v1.4.0 | P4-2: Migration Framework | 329 |
| v1.4.1 | P6-1: PaperBroker + Reconciliation | 338 |
| v1.4.3 | P6-2: Phase Guard E2E | 344 |
| v1.4.6 | P4-3: Postgres Adapter | 348 |
| v1.4.7 | P5-4: Metrics Dashboard | 354 |
| v1.4.8 | P3-5: Regime Benchmark | 355 |
| v1.4.9 | P6-5: Paper Trading E2E | 358 |
| **v1.4.10** | **P4-3-ext: Postgres Schema** | **360** |
