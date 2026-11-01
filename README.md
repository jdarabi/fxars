# FX-ARS — سامانه تحلیل، ارزیابی و پشتیبانی تصمیم معاملات فارکس

پیاده‌سازی مرجع پروژه **FX-ARS-SRS-ARCH-002** با پایتون؛ فاز **MVP-1 (Read-only)** به‌صورت کامل و اجراشدنی، به‌همراه اسکلت فازهای بعد (Paper/Demo/Assisted) با دروازه‌های فاز.

> این سامانه ابزار پشتیبانی تصمیم و پژوهش است؛ نه تضمین سود، نه توصیه سرمایه‌گذاری و نه ارسال سفارش در MVP-1. خروجی معتبر همیشه شامل «عدم معامله / NO TRADE» است.

## خلاصه قابلیت‌ها

| حوزه | پیاده‌سازی |
|---|---|
| داده بازار | قرارداد Candle، اعتبارسنجی OHLC/زمان/اسپرد، قرنطینه داده نامعتبر، نسخه‌بندی اصلاحات، Raw append-only، گزارش کیفیت داده |
| تقویم | سشن‌های جهانی با DST (zoneinfo)، تعطیلات، کندل‌های مورد انتظار، تازگی داده متناسب با تعطیلی بازار |
| تحلیل | Swing، BOS/CHoCH، FVG، Order Block، Liquidity Sweep، Displacement، روند/مومنتوم/نوسان/حجم، سطوح کلیدی، بنیادی، بین‌بازاری |
| شواهد | قرارداد Evidence با زمان مشاهده/دسترس‌پذیری، ابطال، انقضا، پارامتر‌هش و توضیح |
| تصمیم | تجمیع خانواده‌ای با سقف سهم، کنترل تعارض/پوشش/پایداری، NO TRADE صریح |
| سناریو | ماشین حالت DRAFT→WATCH→ARMED→TRIGGERED و ابطال/انقضا/رد، با ثبت Transition |
| ریسک | اندازه موقعیت Decimal، ۲۰ کنترل مستقل، RiskDecision، Kill Switch سراسری |
| پژوهش | بک‌تست رویدادمحور با اسپرد/کمیسیون/سوآپ/لغزش، OOS سه‌بخشی + Embargo، Walk-forward، PBO، DSR، Monte Carlo |
| API/UI | API نسخه‌دار `/api/v1` با RBAC، Idempotency، Rate Limit و داشبورد فارسی RTL |
| ممیزی | Audit زنجیره‌هش فقط‌افزودنی + Transactional Outbox |
| آزمون | ۱۰۰+ آزمون واحد/یکپارچگی/پذیرش با `unittest` (بدون وابستگی خارجی) |

## پیش‌نیاز

- Python **3.11+** (توسعه و آزمون با 3.12)
- بدون کتابخانه خارجی؛ فقط کتابخانه استاندارد (SQLite، http.server، decimal، zoneinfo)

## اجرای سریع

**ویندوز (پیشنهادی):** روی `FXARS.bat` دوبار کلیک کنید. منوی فارسی شامل اجرای داشبورد، تحلیل، ریسک، بک‌تست، ممیزی، آزمون‌ها، **توقف داشبورد** و **خروج** است. داشبورد روی یک پورت آزاد اجرا می‌شود و URL در کنسول چاپ می‌شود. همین فایل دستورات را هم می‌پذیرد:

```powershell
.\FXARS.bat                     # منوی تعاملی
.\FXARS.bat serve --port 8080   # اجرای مستقیم API/داشبورد
.\FXARS.bat analyze --instrument EURUSD --timeframe H1
.\FXARS.bat audit verify
```

خط فرمان مستقیم:

```powershell
# 1) ساخت پایگاه داده و کاربران پایه
python -m fxars init

# 2) تولید داده دمو قطعی (EURUSD H1 + DXY + تقویم اقتصادی) و ورود آن
python -m fxars seed-demo

# 3) تحلیل و سناریو
python -m fxars analyze --instrument EURUSD --timeframe H1

# 4) ارزیابی ریسک سناریوی تولیدشده
python -m fxars risk --scenario <scenario_id> --equity 10000

# 5) بک‌تست + گزارش Markdown/HTML
python -m fxars backtest --instrument EURUSD --timeframe H1 --report

# 6) API + داشبورد
python -m fxars serve --host 127.0.0.1 --port 8080
# سپس http://127.0.0.1:8080/  (نام کاربری/رمز از خروجی init)
```

`init` یک‌بار رمز `admin` (با MFA) و `analyst` را نمایش می‌دهد. کد MFA فعلی:

```powershell
python -m fxars auth code --username admin
```

## معماری

Modular Monolith با مرزهای دامنه و قراردادهای نسخه‌دار:

```
fxars/
  core/          خطا، زمان UTC، Decimal، هش، شناسه، لاگ، serde
  domain/        موجودیت‌ها و قواعد تغییرناپذیر
  config/        پیکربندی نسخه‌دار و config_hash
  instruments/   مشخصات قراردادی نماد، تقویم و سشن‌ها
  data/          قرارداد کندل، کیفیت داده، دریافت، Snapshot، تولید داده دمو
  storage/       SQLite، schema، Repositoryها
  analysis/      اندیکاتورها، ساختار، سطوح، رژیم، بنیادی، بین‌بازاری، Evidence
  decision/      تجمیع، سناریو، ماشین حالت، Trigger
  risk/          سیاست، اندازه موقعیت، دروازه، مواجهه، Kill Switch
  research/      بک‌تست، معیارها، پروتکل OOS، Walk-forward، PBO/DSR، Monte Carlo
  audit/         Audit hash-chain و Outbox
  services/      سرویس‌های کاربردی تحلیل و سناریو
  execution/     اسکلت MVP-2+ با Phase Guard
  identity/      RBAC، رمز، TOTP، نشست
  api/           HTTP API، OpenAPI، خطاها
  ui/            داشبورد SPA
  cli/           خط فرمان
```

جزئیات: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — الگوریتم‌ها: [docs/ALGORITHMS.md](docs/ALGORITHMS.md)

## اصول اجراشده

- **Fail-Safe:** داده کهنه/ناکافی/نامعتبر ⇒ NO TRADE.
- **Determinism:** Seed ثبت‌شده؛ `analysis_run_id`، `result_hash` و `evidence_id` از محتوا مشتق می‌شوند و اجرای دوباره با ورودی یکسان خروجی یکسان می‌دهد (AC-02).
- **Explainability:** هر تصمیم با شواهد، سهم خانواده‌ها، تعارض‌ها و دلیل NO TRADE.
- **No Look-ahead:** هر شاهد `observed_at` و `available_at` دارد؛ بک‌تست فقط داده در دسترس را می‌بیند و ورود در کندل بعد انجام می‌شود.
- **Risk Gate مستقل:** حتی با فراخوانی مستقیم سرویس، بدون RiskDecision تأییدشده و معتبر، OrderIntent ساخته نمی‌شود.
- **MVP-1 بدون ارسال سفارش:** `Phase.READ_ONLY` در سرویس اجرا enforce می‌شود (AC-05).

## آزمون‌ها

```powershell
python -m unittest discover -s tests -v      # کل آزمون‌ها
python -m unittest tests.test_acceptance -v  # AC-01..AC-12
python -m fxars selftest                     # همان کل آزمون‌ها از CLI
```

## پیکربندی

پیش‌فرض‌ها در `fxars/config/settings.py`؛ بازنویسی با `config/settings.json` (نمونه: `config/settings.example.json`) یا متغیرهای محیطی:

| متغیر | اثر |
|---|---|
| `FXARS_PHASE` | `READ_ONLY` / `PAPER` / `DEMO` / `ASSISTED` / `AUTOMATED_LIMITED` |
| `FXARS_DB_PATH` | مسیر SQLite |
| `FXARS_SECRET_KEY` | کلید رمزنگاری اسرار (TOTP) |
| `FXARS_API_HOST` / `FXARS_API_PORT` | آدرس API |
| `FXARS_SEED` | Seed پیش‌فرض |

**هشدار:** کلید پیش‌فرض فقط برای توسعه است؛ در استقرار واقعی از Secret Manager/KMS استفاده کنید.

## محدودیت‌ها (خلاصه)

- داده دمو شبیه‌سازی‌شده است و نماینده بازار واقعی نیست.
- فید واقعی بروکر/داده در این تحویل وصل نشده؛ نقطه اتصال `MarketDataProvider` و `BrokerAdapter` است.
- اسکیل/چندمستاجری تجاری (MVP-4) خارج از دامنه این تحویل است.
- بک‌تست تضمین عملکرد آینده نیست؛ Forward Test الزامی است.

فهرست کامل: [docs/LIMITATIONS.md](docs/LIMITATIONS.md)

## مستندات

| سند | موضوع |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | معماری، لایه‌ها، جریان داده، مدل اطلاعاتی |
| [docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md) | قرارداد Candle/رویداد/Evidence/Scenario، قواعد کیفیت |
| [docs/ALGORITHMS.md](docs/ALGORITHMS.md) | مشخصات عملیاتی ماژول‌های تحلیل و تجمیع |
| [docs/RISK_POLICY.md](docs/RISK_POLICY.md) | فرمول sizing، کنترل‌ها، Kill Switch |
| [docs/VALIDATION_PROTOCOL.md](docs/VALIDATION_PROTOCOL.md) | OOS، Walk-forward، DSR/PBO، Monte Carlo |
| [docs/API.md](docs/API.md) | نقاط پایانی، احراز هویت، خطاها، نمونه‌ها |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | نصب، پشتیبان‌گیری، بازیابی، Runbook |
| [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) | نگاشت AC-01..AC-12 به آزمون‌ها |
| [docs/DECISIONS.md](docs/DECISIONS.md) | تصمیم‌های باز سند و انتخاب‌های پیاده‌سازی |
| [docs/PHASES.md](docs/PHASES.md) | نقشه راه MVP-1..4 و دروازه‌ها |
| [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | محدودیت‌های شناخته‌شده |
| [docs/IMPLEMENTATION_REPORT.md](docs/IMPLEMENTATION_REPORT.md) | گزارش پیاده‌سازی و نتایج آزمون/دمو |

## وضعیت

- MVP-1: پیاده‌سازی کامل read-only، آزمون‌شده.
- MVP-2+: قرارداد و اسکلت آماده؛ فعال‌سازی تنها پس از عبور از دروازه‌های مربوطه.
