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

کدها: `VALIDATION_ERROR`, `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `DATA_STALE`, `DATA_INVALID`, `RISK_REJECTED`, `KILL_SWITCH_ACTIVE`, `PHASE_VIOLATION`, `IDEMPOTENCY_CONFLICT`, `RATE_LIMITED`, `INTERNAL_ERROR`.

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
| GET/POST | `/api/v1/killswitch` | scenario.read / killswitch.toggle | وضعیت/تغییر |

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

## داشبورد

`GET /` یک SPA فارسی RTL است: تحلیل، سناریو، ریسک، بک‌تست و عملیات. توکن در `localStorage` نگهداری می‌شود.

## محدودیت‌ها

- Rate limit پیش‌فرض ۱۲۰ درخواست در دقیقه به‌ازای توکن/IP.
- حداکثر بدنه ۱ مگابایت.
- صفحه‌بندی `limit`/`offset` با سقف ۵۰۰.
