# پیاده‌سازی سند تکمیلی ۱.۱ — ماتریس ردیابی

مبنا: «سند تکمیلی ارتقای سامانه هوشمند تحلیل، ارزیابی و پشتیبانی تصمیم در بازار فارکس» نسخه ۱.۱.
این سند نشان می‌دهد هر بند تکمیلی کجای کد پیاده شده، با چه آزمونی اثبات می‌شود و چه قرارداد بیرونی (API/CLI/UI) دارد.

وضعیت: **پیاده‌سازی‌شده (MVP تکمیلی)**. مفروضات و موارد باقی‌مانده در پایان همین فایل و در `docs/LIMITATIONS.md` آمده است.

---

## ۱. اصول حاکم

| اصل | پیاده‌سازی | شاهد |
|---|---|---|
| No-Trade First | دروازه `DATA_UNTRUSTED`، `UNCERTAINTY_TOO_HIGH`، `NO_TRADE` در تجمیع و RISK Gate؛ هیچ مسیر جایگزینی برای دور زدن ندارد | `fxars/services/analysis.py`، `fxars/risk/gate.py`، `tests/test_decision.py` |
| Decision Provenance | زنجیره هش فقط‌افزودنی `decision_provenance`؛ هر تحلیل در همان تراکنش ذخیره می‌شود | `fxars/governance/provenance.py`، `fxars/services/analysis.py` |
| Uncertainty Budget | بودجه پنج‌جزئی `U = αU_data + βU_model + γU_regime + δU_conflict + εU_execution`؛ عبور از سقف ⇒ حداقل WAIT/NO_TRADE | `fxars/decision/uncertainty.py` |
| Fail-Safe | خطا در محاسبه DTS/عدم‌قطعیت/قفل ریسک به رد تصمیم یا فعال‌شدن قفل منجر می‌شود، نه عبور | `fxars/service*`، `fxars/risk/gate.py` |

---

## ۲. ماتریس پوشش بندها

ستون «آزمون» فایل آزمون نهایی این نسخه است.

| بند | نیازمند | پیاده‌سازی اصلی | قرارداد بیرونی | آزمون |
|---|---|---|---|---|
| ۱ | اصول سه‌گانه (No-Trade First، Provenance، Uncertainty Budget) | `fxars/config/decision.py`، `fxars/decision/uncertainty.py`، `fxars/governance/provenance.py` | `/api/v1/governance/provenance/{run_id}` | `tests/test_governance.py`، `tests/test_decision_policy.py` |
| ۲ | دامنه تنگ‌شده MVP و معیارهای خروج عددی | `docs/MVP.md`، `AcceptancePolicy` | `python -m fxars research-gate RUN_ID --strict` | `tests/test_acceptance_gates.py` |
| ۳ | اجزای جدید: Evidence Graph، Scenario Ledger، Decision Provenance Store، Uncertainty Engine، Regime Meta-Controller، Counterfactual Replay، Model/Policy Registry، Kill Switch سطح‌دار | `fxars/decision/evidence_graph.py`، `fxars/decision/score.py`، `fxars/decision/uncertainty.py`، `fxars/decision/intelligence.py`، `fxars/governance/*`، `fxars/risk/killswitch.py` | تب «هوشمندی تصمیم» در داشبورد + APIهای `/api/v1/intelligence/*` و `/api/v1/governance/*` | `tests/test_intelligence.py`، `tests/test_api.py` |
| ۴ | Data Contract و Data Trust Score با دروازه `DATA_UNTRUSTED` | `fxars/data/trust.py`، `TrustPolicy`، `AnalysisService` | `analysis_meta.data_trust` در پاسخ تحلیل | `tests/test_decision_policy.py` |
| ۵ | تعریف پنج‌جزئی شاهد (E، R، F، منبع، ابطال/انقضا) | `Evidence` موجود + `build_evidence_graph` و `composite_score` | `analysis_meta.evidence_graph` و `composite_score` | `tests/test_decision_policy.py` |
| ۶ | Model Risk Tiering ۰–۳، Model Card، کالیبراسیون، Drift، Shadow/Canary، عدم‌قطعیت رژیم | `fxars/governance/models.py`، `fxars/decision/uncertainty.py` | `GET/POST /api/v1/governance/models` | `tests/test_governance.py` |
| ۷ | امتیاز ترکیبی `S = Σw·E·R·F − P_conflict` و بودجه عدم‌قطعیت | `fxars/decision/score.py`، `fxars/decision/uncertainty.py` | `analysis_meta.composite_score` / `uncertainty` | `tests/test_decision_policy.py` |
| ۸ | خروجی استاندارد تصمیم (جهت، اطمینان، عدم‌قطعیت، منشأ، سناریو، دلیل NO_TRADE) | `AnalysisService._persist` + `decision_provenance` | پاسخ `POST /api/v1/analysis-runs` و صفحه تصمیم | `tests/test_governance.py`، `tests/test_api.py` |
| ۹ | اندازه موقعیت با هزینه‌ها و دروازه ریسک گسترده (شامل زیان هفتگی و سشن) | `fxars/risk/sizing.py`، `fxars/risk/gate.py` (`weekly_loss_within_limit`، `market_open`، `risk_lock_clear`) | `POST /api/v1/risk/evaluate` | `tests/test_risk.py`، `tests/test_risk_lock.py` |
| ۱۰ | کنترل زیان هفتگی، خوشه مواجهه، سشن و رویداد | `RiskLockMachine.evaluate` + `RiskService._weekly_loss_fraction` + کنترل‌های `currency_exposure_ok`/`correlation_exposure_ok`/`event_blackout_ok`/`market_open` | `GET/POST /api/v1/risk/lock` | `tests/test_risk_lock.py` |
| ۱۱ | Kill Switch سه‌سطحی SYSTEM/MODULE/ACCOUNT | `fxars/risk/killswitch.py` (`all_status`, `is_active(scope,target)`) | `GET/POST /api/v1/killswitch` با `scope`/`target` | `tests/test_risk_lock.py` |
| ۱۲ | پروتکل بک‌تست، آستانه‌های عددی پذیرش و ضدالگوها؛ حاکمیت سیاست | `fxars/research/acceptance.py`، `fxars/governance/policy.py` | `GET /api/v1/governance/acceptance/{run_id}`، `research-gate`، `/api/v1/governance/policies` | `tests/test_acceptance_gates.py`، `tests/test_governance.py` |
| ۱۳ | محافظ‌های اجرا (Idempotency، Retry/Outbox، Reconciliation، تفکیک Demo/Real) و قرارداد API/UX | `fxars/execution/*`، `fxars/api/server.py`، `fxars/ui/dashboard.py` | همان APIها + تب هوشمندی | `tests/test_execution.py`، `tests/test_api.py` |
| ۱۴ | امنیت، حاکمیت، SLO، نقشه راه و ردیابی آزمون | `docs/OPERATIONS.md`، این سند، `docs/PHASES.md` | `python -m fxars security-audit` | `tests/test_acceptance.py`، `tests/test_kms.py` |

> شماره بندها با ساختار موضوعی سند ۱.۱ هم‌راستا شده است؛ جاهایی که کد مستقیماً به شماره بند ارجاع می‌دهد (مثلاً §۴-۲، §۶، §۷-۱، §۷-۲، §۹-۲، §۱۲-۲) همان شماره در docstring ماژول حفظ شده است.

---

## ۳. آستانه‌های عددی پیش‌فرض

همه در `fxars/config/decision.py` و بخش `decision` فایل پیکربندی قابل بازنویسی‌اند. تغییر هر آستانه باید نسخه‌دار و در `config_hash` ثبت شود.

### ۳-۱. Data Trust Score

| پارامتر | پیش‌فرض |
|---|---|
| `min_score` | ۰٫۶۰ |
| `freshness_max_age_bars` | ۲ کندل |
| وزن‌ها | تازگی ۰٫۳۰، کامل‌بودن ۰٫۲۰، سازگاری ۰٫۲۰، اعتبار schema ۰٫۱۵، اتکای منبع ۰٫۱۵ |
| `max_gap_bars` | ۳ |
| `max_spread_jump_ratio` | ۳ برابر میانه |

`status` یکی از `TRUSTED` / `DEGRADED` / `UNTRUSTED` است. فقط دو وضعیت اول اجازه تحلیل می‌دهند.

### ۳-۲. بودجه عدم‌قطعیت

| پارامتر | پیش‌فرض |
|---|---|
| `max_total` | ۰٫۶۰ |
| `wait_threshold` | ۰٫۴۵ |
| وزن‌ها (α..ε) | داده ۰٫۳۰، مدل ۰٫۱۵، رژیم ۰٫۲۰، تعارض ۰٫۲۰، اجرا ۰٫۱۵ |
| عدم‌قطعیت مدل بدون کالیبراسیون | ۰٫۵۰ |
| آستانه هزینه اجرا | ۰٫۲۵ |

`level`: LOW / MEDIUM / HIGH / CRITICAL. HIGH و CRITICAL در MVP به `NO_TRADE` با کد `UNCERTAINTY_TOO_HIGH` نگاشت می‌شوند؛ سامانه حالت مستقل WAIT ندارد.

### ۳-۳. پذیرش پژوهش

| معیار | آستانه |
|---|---|
| حداقل معامله OOS | ۲۰۰ |
| Profit Factor | ≥ ۱٫۲ |
| حداکثر افت سرمایه | ≤ ۱۵٪ |
| شارپ | > ۰ |
| کالیبراسیون ECE | ≤ ۰٫۰۵ |
| افت آموزش→آزمون | ≤ ۵۰٪ |
| هزینه‌ها | باید غیرصفر و مدل‌شده باشند |
| OOS | الزامی؛ نتیجه TRAIN پذیرفته نمی‌شود |

---

## ۴. جریان تصمیم

1. `AnalysisService.run` کندل‌های بسته و مجاز را می‌خواند.
2. `compute_data_trust` پنج مؤلفه را می‌سنجد؛ `UNTRUSTED` ⇒ `NO_TRADE/DATA_UNTRUSTED`.
3. `build_evidence_graph` شواهد را گره/یال می‌کند و شواهد تکراری را علامت می‌زند.
4. `composite_score` امتیاز ترکیبی و سهم هر خانواده را می‌سازد.
5. `compute_uncertainty` بودجه را محاسبه می‌کند؛ عبور از سقف ⇒ `NO_TRADE`.
6. تجمیع موجود، سناریو/NO TRADE را صادر می‌کند.
7. در همان تراکنش: `AnalysisRun`، شواهد، سناریو، `DecisionProvenance`، Audit و Outbox ذخیره می‌شوند.

خروجی تحلیل شامل `analysis_meta` با کلیدهای `data_trust`، `evidence_graph`، `composite_score` و `uncertainty` است.

## ۵. ارزیابی ریسک و قفل

`RiskService.evaluate` پیش از فراخوانی دروازه:

- زیان روزانه را از `AccountSnapshot.daily_pnl` به کسر سرمایه تبدیل می‌کند.
- زیان هفتگی محقق‌شده را از `closed_trades` ابتدای هفته سشن محاسبه می‌کند.
- `RiskLockMachine.evaluate` را با زیان روزانه/هفتگی، افت سرمایه و وضعیت Kill Switch به‌روز می‌کند.

دروازه ریسک علاوه بر کنترل‌های قبلی این‌ها را اضافه می‌کند:

| کنترل | معنا | کد دلیل |
|---|---|---|
| `risk_lock_clear` | قفل ریسک در وضعیت مسدودکننده نباشد | `RISK_LOCK_ACTIVE` |
| `weekly_loss_within_limit` | زیان هفتگی ≤ ۳× سقف زیان روزانه (سقف ۱۰۰٪) | `WEEKLY_LOSS_LIMIT` |
| `market_open` | بازار باز است یا حداکثر `data_grace_seconds` از آخرین بازبودن گذشته | `MARKET_CLOSED` |

چرخه قفل: `NORMAL → WARNING → LOCKED_DAILY → LOCKED_WEEKLY → KILL_SWITCH → MANUAL_REVIEW`.
`LOCKED_*`، `KILL_SWITCH` و `MANUAL_REVIEW` ارسال سفارش را متوقف می‌کنند و فقط با `POST /api/v1/risk/lock` و دلیل ثبت‌شده آزاد می‌شوند.

Kill Switch در سه سطح `SYSTEM`، `MODULE:<name>` و `ACCOUNT:<id>` ذخیره می‌شود. `is_active()` بدون آرگومان اگر هر سطحی فعال باشد `True` برمی‌گرداند (Fail-Safe).

## ۶. حاکمیت مدل و سیاست

- **Policy Registry:** هر سیاست با نسخه، هش محتوا، وضعیت و امضای ثبت‌کننده ذخیره می‌شود؛ فقط یک نسخه فعال در هر نوع.
- **Model Card:** شامل هدف، مالک، داده آموزش، schema ویژگی، محدودیت‌ها، معیارها، کالیبراسیون و `dataset_snapshot`.
- **Tier 0–3:** Tier 3 در MVP ممنوع است؛ Tier 2 نیازمند تأیید مستقل و کالیبراسیون؛ فعال‌سازی نیازمند عبور از Shadow/Canary.
- **Drift:** `record_drift` رخداد انحراف را در `model_drift` ثبت می‌کند.

## ۷. منشأ تصمیم

هر رکورد `DecisionProvenance` شامل `analysis_run_id`، `decision_id`، `scenario_id`، وضعیت، کدهای دلیل، `data_cutoff`، وضعیت کیفیت داده، رژیم، ارجاع گراف شواهد، مؤلفه‌های عدم‌قطعیت، `config_hash`، نسخه کد/مدل و هش قبلی است. زنجیره با `GET /api/v1/governance/provenance/{run_id}` و `verify_chain` قابل بررسی است؛ دست‌کاری هر رکورد زنجیره را می‌شکند.

## ۸. بک‌تست و پذیرش

`evaluate_acceptance` کنترل‌های OOS_SAMPLE، PROFIT_FACTOR، MAX_DRAWDOWN، SHARPE_POSITIVE، CALMAR، CALIBRATION_ECE، TRAIN_TEST_GAP و COSTS_MODELED را اجرا می‌کند و ضدالگوهای TINY_SAMPLE، OVERFIT_GAP، IGNORED_COSTS، NO_LOCKED_TEST، NO_WALKFORWARD و SINGLE_REGIME را گزارش می‌دهد.

```powershell
python -m fxars research-gate <run_id>
python -m fxars research-gate <run_id> --strict   # خروج ۲ در صورت رد
```

## ۹. API و داشبورد

| مسیر | کارکرد |
|---|---|
| `GET/POST /api/v1/intelligence/journal` | دفتر تصمیم |
| `GET /api/v1/intelligence/heatmap` | نقشه حرارتی سناریوها |
| `GET /api/v1/intelligence/premortem/{run_id}` | پیش‌مرگ‌نگاری |
| `GET /api/v1/intelligence/counterfactual/{scenario_id}` | بازپخش ضدواقعی |
| `GET/POST /api/v1/intelligence/challenges/{scenario_id}` | حالت چالش |
| `GET /api/v1/governance/provenance/{run_id}` | زنجیره منشأ |
| `GET/POST /api/v1/governance/policies` | ثبت/فعال‌سازی سیاست |
| `GET/POST /api/v1/governance/models` | ثبت/ارتقای مدل |
| `GET /api/v1/governance/acceptance/{run_id}` | دروازه پذیرش |
| `GET/POST /api/v1/risk/lock` | وضعیت/تغییر قفل ریسک |

داشبورد تب «هوشمندی تصمیم» را با همین قابلیت‌ها و پنل عدم‌قطعیت/اعتماد داده نمایش می‌دهد.

## ۱۰. امنیت، SLO و نقشه راه

- **SLO پیشنهادی:** دسترس‌پذیری API ۹۹٫۵٪ ماهانه؛ p95 تحلیل < ۲ ثانیه روی H1 با ۵۰۰ کندل؛ p95 ریسک < ۳۰۰ms؛ نرخ خطای 5xx < ۰٫۵٪.
- **امنیت:** RBAC سمت سرور، TOTP برای نقش‌های حساس، هش رمز PBKDF2، زنجیره ممیزی و لنگر HMAC، KMS قابل چرخش، عدم ثبت اسرار.
- **نقشه راه:** PostgreSQL/Rate Limit مشترک، KMS ابری/HSM، Tier 3 با مصوبه حاکمیت، کالیبراسیون مدل زنده، اتصال SLO به متریک‌های Prometheus-سازگار.

## ۱۱. محدودیت‌ها و مفروضات

- سامانه حالت مستقل `WAIT` ندارد؛ سطوح HIGH/CRITICAL عدم‌قطعیت به `NO_TRADE` نگاشت می‌شوند.
- DTS روی کندل‌های مصرف‌شده محاسبه می‌شود، نه کل تاریخچه؛ برای تحلیل بلندمدت باید پنجره را آگاهانه انتخاب کرد.
- `weekly_loss` از معاملات بسته‌شده محقق محاسبه می‌شود؛ سود/زیان شناور در `AccountSnapshot.daily_pnl` و افت سرمایه دیده می‌شود.
- Tier 3 در MVP عمداً ممنوع است؛ فعال‌سازی آن نیازمند تغییر سیاست حاکمیت و آزمون مستقل است.
- آستانه‌های پذیرش «پیشنهادی» هستند و باید پیش از مشاهده Locked Test توسط مالک ریسک/پژوهش تثبیت شوند.
