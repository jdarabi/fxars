# مستندات API

نسخه قرارداد: `1.0.0` — مسیرها: `/api/v1` — مشخصات ماشین‌خوان: `GET /openapi.json`

## احراز هویت

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username": "analyst", "password": "...", "totp_code": "123456"}
```

پاسخ: `token`, `expires_at`, `user`, `permissions`. سپس:

```http
Authorization: Bearer <token>
```

نقش‌های ADMIN / RISK_MANAGER / OPERATOR نیازمند TOTP هستند. نشست با `POST /api/v1/auth/logout` باطل می‌شود.

## خطاها

```json
{"error": {"code": "DATA_STALE", "message": "...", "correlation_id": "...", "details": {...}}}
```

کدها: `VALIDATION_ERROR`, `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `DATA_STALE`, `DATA_INVALID`, `RISK_REJECTED`, `KILL_SWITCH_ACTIVE`, `PHASE_VIOLATION`, `IDEMPOTENCY_CONFLICT`, `RATE_LIMITED`, `QUOTA_EXCEEDED`, `TENANT_INACTIVE`, `INTERNAL_ERROR`.

همه پاسخ‌ها هدر `X-Correlation-ID` دارند.

## نقاط پایانی

| متد | مسیر | مجوز | کارکرد |
|---|---|---|---|
| GET | `/api/v1/health` | عمومی | سلامت، فاز، وضعیت ممیزی |
| POST | `/api/v1/auth/login` | عمومی | ورود |
| POST | `/api/v1/auth/demo-login` | عمومی (dev + localhost) | ورود سریع دمو برای ANALYST/AUDITOR بدون افشای رمز |
| GET | `/api/v1/auth/demo-totp` | عمومی (dev + localhost) | کد TOTP جاری کاربر MFA (مثلاً admin) برای سهولت دمو |
| POST | `/api/v1/auth/logout` | کاربر | خروج |
| GET | `/api/v1/auth/me` | کاربر | کاربر و مجوزها |
| GET | `/api/v1/meta` | data.read | نسخه‌ها، فاز، سیاست ریسک، مشخصات ماژول‌ها |
| GET | `/api/v1/instruments` | data.read | نمادها و مشخصات قراردادی |
| GET/POST | `/api/v1/phase` | data.read / settings.write | خواندن یا تغییر فاز با اعمال فوری در زمان اجرا |
| GET | `/api/v1/trading/settings?equity=N` | data.read | تنظیمات معاملات، سقف‌های سیاست و پیشنهاد هوشمند سرمایه |
| POST | `/api/v1/trading/settings` | settings.write | ذخیره/اعمال تنظیمات معاملات؛ عبور از سقف سیاست با هشدار و تأیید صریح |
| GET | `/api/v1/trading/status` | scenario.read | وضعیت بروکر/MT5 و حساب |
| GET | `/api/v1/market-data/candles` | data.read | کندل با فیلتر نماد/تایم‌فریم/بازه |
| GET | `/api/v1/data-quality/runs` | data.read | گزارش کیفیت داده |
| GET | `/api/v1/analysis-runs` | scenario.read | فهرست اجراها |
| POST | `/api/v1/analysis-runs` | analysis.run | اجرای تحلیل (Idempotency-Key الزامی) |
| GET | `/api/v1/analysis-runs/{id}` | scenario.read | نتیجه و شواهد |
| GET | `/api/v1/scenarios` | scenario.read | فهرست/خلاصه وضعیت |
| GET | `/api/v1/scenarios/{id}` | scenario.read | سناریو، Transitionها، RiskDecision |
| POST | `/api/v1/scenarios/{id}/evaluate` | scenario.transition | ارزیابی Trigger/Invalidation/Expiry |
| POST | `/api/v1/scenarios/{id}/transition` | scenario.transition | گذار دستی مجاز با دلیل |
| POST | `/api/v1/risk/evaluate` | risk.evaluate | ارزیابی ریسک (بدون سفارش) |
| GET | `/api/v1/risk/decisions` | scenario.read | فهرست تصمیم‌های ریسک |
| GET | `/api/v1/risk/decisions/{id}` | scenario.read | جزئیات |
| GET/POST | `/api/v1/backtests` | report.read / backtest.run | فهرست/ایجاد بک‌تست |
| GET | `/api/v1/backtests/{id}` | report.read | نتیجه کامل |
| GET | `/api/v1/backtests/{id}/report?format=html\|md` | report.read | گزارش |
| GET | `/api/v1/audit-events` | audit.read | ممیزی + وضعیت زنجیره |
| GET/POST | `/api/v1/killswitch` | scenario.read / killswitch.toggle | وضعیت/تغییر با `scope`=`SYSTEM\|MODULE\|ACCOUNT` و `target` |
| GET/POST | `/api/v1/risk/lock` | scenario.read / risk.evaluate | وضعیت قفل ریسک یا ثبت بازبینی/آزادسازی با دلیل |
| GET/POST | `/api/v1/intelligence/journal` | scenario.read / scenario.transition | دفتر تصمیم (فیلتر run/scenario) |
| GET | `/api/v1/intelligence/heatmap` | scenario.read | نقشه حرارتی سناریوها و تراکم |
| GET | `/api/v1/intelligence/premortem/{run_id}` | scenario.read | پیش‌مرگ‌نگاری تحلیل |
| GET | `/api/v1/intelligence/counterfactual/{scenario_id}` | scenario.read | بازپخش ضدواقعی (`max_bars`) |
| GET/POST | `/api/v1/intelligence/challenges/{scenario_id}` | scenario.read / scenario.transition | فهرست/ثبت چالش سناریو |
| GET | `/api/v1/governance/provenance/{run_id}` | audit.read | رکوردهای منشأ و وضعیت زنجیره |
| GET/POST | `/api/v1/governance/policies` | audit.read / risk.policy.write | فهرست، ثبت و فعال‌سازی سیاست |
| GET/POST | `/api/v1/governance/models` | audit.read / risk.policy.write | Model Card، ارتقا و Drift |
| GET | `/api/v1/governance/acceptance/{run_id}` | report.read | دروازه پذیرش بک‌تست |
| GET | `/api/v1/tenant` | data.read | پلن، سقف و مصرف مستاجر جاری |
| GET | `/api/v1/tenant/export?limit=N` | data.read | خروجی JSON داده مستاجر جاری (بدون اسرار) |
| GET | `/api/v1/tenant/retention` | data.read | سیاست نگهداری و حجم داده مستاجر جاری |
| GET | `/api/v1/tenants` | tenant.admin | فهرست همه مستاجران با پلن/مصرف |
| POST | `/api/v1/tenants/{id}` | tenant.admin | تغییر پلن، فعال/غیرفعال یا quota_overrides |
| GET | `/api/v1/tenants/{id}/export` | tenant.admin | خروجی داده مستاجر مشخص |
| GET | `/api/v1/tenants/{id}/retention` | tenant.admin | گزارش نگهداری مستاجر مشخص |

> در MVP-1 هیچ端点 اجرای سفارش وجود ندارد؛ درخواست `/api/v1/orders` پاسخ 404 می‌دهد.

## Idempotency

برای همه POSTهای احرازشده هدر `Idempotency-Key` الزامی است. تکرار با همان کلید و بدنه، همان پاسخ قبلی را برمی‌گرداند؛ بدنه متفاوت ⇒ `409 IDEMPOTENCY_CONFLICT`.

```http
POST /api/v1/analysis-runs
Idempotency-Key: 8f14e45f-ea1c-4f7a-9d2b-...
```

## حالت دمو (فقط توسعه)

دو端点 کمکی برای سهولت اجرای دمو وجود دارد که **فقط** وقتی `environment == "dev"` و درخواست از `localhost` باشد فعال‌اند:

- `POST /api/v1/auth/demo-login` با بدنه `{"role":"ANALYST"}` → توکن نشست (فقط ANALYST/AUDITOR؛ مدیر باید MFA بدهد).
- `GET /api/v1/auth/demo-totp?username=admin` → `{code, expires_in}` برای ورود سریع مدیر در دمو.

در محیط `prod` این مسیرها با `401` رد می‌شوند و هر صدور کد در Audit با `DEMO_TOTP_ISSUED` ثبت می‌شود. برای استقرار واقعی، `environment` را غیر از `dev` تنظیم کنید.

## نمونه: تحلیل

```bash
curl -s http://127.0.0.1:8080/api/v1/analysis-runs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: demo-1" \
  -H "Content-Type: application/json" \
  -d '{"instrument_id":"EURUSD","timeframe":"H1"}'
```

پاسخ شامل `run` (status، snapshot، config_hash، result_hash)، `decision` (action، score، coverage، reasons)، `scenario` و فهرست `evidences` است.

## نمونه: ارزیابی ریسک

```json
{
  "scenario_id": "sc_...",
  "account": {
    "equity": "10000", "balance": "10000", "free_margin": "10000",
    "taken_at": "2026-11-01T12:00:00Z", "currency": "USD",
    "leverage": "100", "open_positions": 0, "positions": []
  },
  "rates": {"USD": "1"}
}
```

## نمونه: تنظیمات هوشمند معاملات

`GET /api/v1/trading/settings` تنظیمات ذخیره‌شده `automated_limited`، سقف‌های `settings.risk` و پیشنهاد محاسبه‌شده از روی سرمایه را برمی‌گرداند. اگر `equity` داده نشود، آخرین `AccountSnapshot` و در نبود آن مقدار پیش‌فرض با `equity_source=fallback` استفاده می‌شود.

```json
{
  "equity": "100",
  "equity_source": "account_snapshot",
  "recommendation": {
    "profile": {"key": "micro", "label": "خرد (زیر ۲۰۰ دلار)"},
    "risk_per_trade": "0.05",
    "max_volume_per_order": "0.04",
    "max_open_positions": 1,
    "max_daily_trades": 2,
    "timeframes": ["M15", "H1"],
    "ladder": [{"stop_pips": 10, "volume": "0.05", "estimated_risk": "5.00"}]
  }
}
```

`POST /api/v1/trading/settings` فقط کلیدهای مجاز را می‌پذیرد و در همان اجرا روی سرویس استراتژی و daemon اعمال می‌کند. اعتبارسنجی دو سطحی است:

- **خطای ساختاری (۴۰۰):** مقدار صفر/منفی، تعداد پوزیشن یا معاملهٔ روزانهٔ کمتر از ۱، نماد بدون مشخصات در پایگاه داده، یا تایم‌فریم ناشناخته.
- **هشدار سیاست (۲۰۰ + `requires_confirmation`):** مقدار معتبر است اما از سقف/پیشنهاد `settings.risk` بیرون است (ریسک، زیان روزانه، افت سرمایه، تعداد پوزیشن/معامله، اسپرد، حجم بیش از سقف نماد، یا نماد خارج از فهرست پیشنهادی). تا زمانی که همان درخواست با `confirm_warnings: true` تکرار نشود، هیچ تغییری روی دیسک نوشته نمی‌شود.

```json
{"automated_limited": {
  "max_volume_per_order": "0.04", "max_open_positions": 1, "max_daily_trades": 2,
  "risk_per_trade": "0.05", "daily_loss_limit": "0.08", "drawdown_stop": "0.12",
  "max_spread_pips": "3.0", "timeframes": ["M5", "M15", "H1"],
  "instruments": ["EURUSD", "GBPUSD", "USDJPY"]
}}
```

پاسخ در حالت نیاز به تأیید:

```json
{"saved": false, "requires_confirmation": true, "warnings": ["تعداد پوزیشن باز (9) از سقف سیاست (2) بیشتر است."]}
```

پس از تأیید، درخواست با `"confirm_warnings": true` تکرار می‌شود و پاسخ `{"saved": true, "warnings": [...], "runtime_phase": "..."}` است. این مسیر فقط تنظیمات فاز را تغییر می‌دهد؛ موتور ریسک (`RiskService`/`RiskGate`) همچنان سقف‌های سخت خود را در زمان ارزیابی و ارسال سفارش اعمال می‌کند.

تغییر `enabled`/`killed` از این مسیر مجاز نیست؛ فعال‌سازی ربات فقط از `POST /api/v1/phase` با تأیید `ENABLE ROBOT` انجام می‌شود.

## نمونه: استراتژی‌های دستی (M5)

سه مسیر `POST /api/v1/strategy/analyze`، `/api/v1/strategy/trade` و `/api/v1/strategy/trade_multi` پارامتر اختیاری `strategy` را می‌پذیرند. خالی یا حذف‌شده یعنی انتخاب خودکار بهترین استراتژی بر اساس بک‌تست.

```json
{"instrument_id": "EURUSD", "timeframe": "M5", "bars": 2000, "strategy": "EMA20/FullBody"}
```

- `EMA20/FullBody`: کندل بدون سایه با بدنه ۱۰–۲۰ پیپ، کاملاً بالای/زیر EMA20؛ SL دو پیپ آن‌سوی کندل و TP دو برابر بدنه.
- `H&S/Reversal`: سر و شانه با شانه راست بالاتر (معکوس) یا پایین‌تر (معمولی) از شانه چپ؛ SL دو پیپ آن‌سوی شانه چپ و TP ۲۰ پیپ.
- این دو استراتژی فقط روی `M5` پذیرفته می‌شوند؛ در غیر این صورت خطای اعتبارسنجی ۴۰۰ برمی‌گردد. پاسخ تحلیل شامل `available` (فهرست استراتژی‌ها) و `selected` (انتخاب دستی) است.

### فیلتر روند H1 برای استراتژی‌های M5

سیگنال هر دو استراتژی دستی فقط در صورت هم‌جهت‌بودن با روند H1 پذیرفته می‌شود: جهت روند از آخرین کندل **بستهٔ** H1 نسبت به EMA50 آن تعیین می‌شود (خرید فقط در روند صعودی، فروش فقط در روند نزولی). برای جلوگیری از نگاه به آینده، فقط کندل‌های H1 با `close_time <= open_time` کندل M5 لحاظ می‌شوند.

- برای `timeframe=M5` سه مسیر استراتژی خودشان کندل‌های H1 را از همان اتصال MT5 می‌گیرند؛ اگر دریافت H1 شکست بخورد، پاسخ `503 BROKER_UNAVAILABLE` است و هیچ سیگنال بدون فیلتر صادر نمی‌شود.
- اگر کندل بستهٔ کافی برای EMA50 نباشد، جهت روند `null` است و ورود مسدود می‌شود (fail-closed).
- پاسخ شامل `trend_filter` است:

```json
{"trend_filter": {"timeframe": "H1", "applied": true, "direction": "DOWN"}}
```

اگر سیگنال خامی وجود داشته باشد ولی به‌دلیل ناهمسویی رد شود، `reason` این موضوع را توضیح می‌دهد. امتیازدهی بک‌تست دو استراتژی دستی نیز با همین فیلتر انجام می‌شود.

## نمونه: هوشمندی تصمیم و حاکمیت

```http
POST /api/v1/intelligence/journal
Content-Type: application/json

{"kind": "PRE_TRADE", "body": "سناریو با وجود هم‌بستگی DXY همچنان معتبر است.", "scenario_id": "sc_..."}
```

`kind` یکی از `NOTE`/`PRE_TRADE`/`POST_TRADE`/`CHALLENGE`/`PRE_MORTEM`/`OVERRIDE` و `severity` یکی از `LOW`/`MEDIUM`/`HIGH`/`CRITICAL` است.

```http
POST /api/v1/intelligence/challenges/sc_...
Content-Type: application/json

{"thesis": "شکست سطح با حجم پایین، احتمال fake breakout را بالا می‌برد.", "severity": "MEDIUM"}
```

```http
POST /api/v1/risk/lock
Content-Type: application/json

{"reason": "زیان هفتگی بازبینی شد؛ ادامه با سقف کمتر", "release": true}
```

```http
POST /api/v1/killswitch
Content-Type: application/json

{"active": true, "scope": "ACCOUNT", "target": "demo-100", "reason": "انحراف اجرای بروکر"}
```

ثبت مدل (Tier 3 در MVP رد می‌شود):

```http
POST /api/v1/governance/models
Content-Type: application/json

{
  "model_id": "regime-meta", "version": "1.0.0", "tier": 2,
  "purpose": "انتخاب رژیم و وزن خانواده شواهد", "owner": "research",
  "training_data": "EURUSD H1 2018-2025", "feature_schema": "features_v2",
  "provides_probability": false, "calibration": {"method": "none"}
}
```

پاسخ `GET /api/v1/governance/provenance/{run_id}` شامل `records` و `chain` است؛ `chain.valid=false` یعنی زنجیره دست‌کاری شده و باید به‌عنوان رخداد امنیتی بررسی شود.

پاسخ `GET /api/v1/governance/acceptance/{run_id}` شامل `passed`، `checks`، `failures`، `anti_patterns` و `thresholds` است.

## داشبورد

`GET /` یک SPA فارسی RTL است: تحلیل، سناریو، ریسک، بک‌تست و عملیات. توکن در `localStorage` نگهداری می‌شود.

## محدودیت‌ها

- Rate limit پیش‌فرض ۱۲۰ درخواست در دقیقه به‌ازای توکن/IP.
- حداکثر بدنه ۱ مگابایت.
- صفحه‌بندی `limit`/`offset` با سقف ۵۰۰.
