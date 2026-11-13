# پروتکل اعتبارسنجی، بک‌تست و کنترل بیش‌برازش

## ۱. تقسیم داده

```
[ Train 60% ][ Embargo ][ Validation 20% ][ Embargo ][ Locked Test 20% ]
```

- انتخاب پارامتر فقط روی Train/Validation.
- Locked Test تا تثبیت نسخه دست‌نخورده می‌ماند؛ هر دسترسی در `locked_test_access` و Audit ثبت می‌شود.
- Embargo (پیش‌فرض ۵ کندل) برای حذف نشت اطلاعات مرزی.
- `assert_disjoint` هم‌پوشانی را رد می‌کند.

## ۲. اجرای بک‌تست

- تصمیم در بسته‌شدن کندل i، ورود در بازشدن کندل i+1.
- فقط Evidence با `available_at ≤ available_at` کندل تصمیم.
- مدل هزینه: اسپرد واقعی/پیش‌فرض، کمیسیون هر لات، سوآپ شبانه، لغزش ورود/خروج.
- اگر در یک کندل هم Stop و هم Target لمس شود، **Stop مقدم** است.
- Partial close در TP1، انتقال Stop به Entry، TP2، انقضا و پایان داده.

خروجی: `BacktestRun` شامل trades، equity curve، metrics، config_hash، data_snapshot_id، seed.

## ۳. معیارها

Net Profit، Return%، Profit Factor (تعریف‌نشده اگر Gross Loss=0)، Expectancy، Win Rate، Avg Win/Loss، Payoff، Max Drawdown، Sharpe، Sortino، Calmar، Exposure، Turnover، Avg R، تفکیک هزینه‌ها.

## ۴. Walk-forward

پنجره‌های Train/Test متحرک (`walkforward_train_bars`, `test_bars`, `step_bars`). در هر fold:
1. گرید پارامترها روی Train ارزیابی می‌شود.
2. بهترین پارامتر (با حداقل تعداد معامله) انتخاب می‌شود.
3. همان پارامتر روی Test اجرا و نتیجه OOS ذخیره می‌شود.

`WalkForwardRunner.sensitivity` حساسیت پارامترهای مجاور را گزارش می‌کند.

## ۵. کنترل بیش‌برازش

- **DSR:** احتمال معنی‌دار بودن Sharpe پس از تعدیل چندآزمونی (Bailey & López de Prado) با `trials` ثبت‌شده.
- **PBO:** CSCV روی ماتریس بازده نسخه‌های پارامتری؛ نسبت تقسیم‌هایی که بهترین IS در OOS زیر میانه است.
- **Monte Carlo:** بازنمونه‌گیری ترتیب معاملات + تنش هزینه؛ صدک‌های سود/MDD و احتمال زیان.

## ۶. حداقل‌های گزارش

- حداقل ۲۰ معامله برای گزارش معنادار (پیکربندی `min_trades_for_report`).
- مقایسه با baseline ساده الزامی است.
- نتیجه OOS مثبت تضمین آینده نیست؛ Forward Test و پایش زنده لازم است.
- معیارهای پذیرش بک‌تست پیش از مشاهده Locked Test ثبت می‌شوند.

## ۷. دروازه پذیرش (سند تکمیلی ۱.۱ §۹-۲)

هیچ نتیجه‌ای «قابل انتشار» نیست مگر `evaluate_acceptance` را عبور کند. آستانه‌ها در `AcceptancePolicy` (بخش `decision.acceptance`) نسخه‌دارند.

| کنترل | قاعده |
|---|---|
| OOS_SAMPLE | نتیجه از TRAIN نباشد و ≥ ۲۰۰ معامله OOS داشته باشد |
| PROFIT_FACTOR | ≥ ۱٫۲ (تعریف‌نشده = رد) |
| MAX_DRAWDOWN | ≤ ۱۵٪ |
| SHARPE_POSITIVE | شارپ > ۰ |
| CALMAR | در صورت تعیین حداقل مثبت، ≥ آن |
| CALIBRATION_ECE | در صورت وجود، ≤ ۰٫۰۵ |
| TRAIN_TEST_GAP | افت PF آموزش→آزمون ≤ ۵۰٪ |
| COSTS_MODELED | کل هزینه‌ها > ۰ و تفکیک‌شده |

### ضدالگوها

| کد | شدت | معنا |
|---|---|---|
| TINY_SAMPLE | HIGH | نمونه کمتر از حداقل آماری |
| OVERFIT_GAP | HIGH | افت شدید عملکرد از آموزش به آزمون |
| IGNORED_COSTS | HIGH | هزینه صفر/مدل‌نشده |
| NO_LOCKED_TEST | MEDIUM | Locked Test استفاده نشده |
| NO_WALKFORWARD | MEDIUM | Walk-forward انجام نشده |
| SINGLE_REGIME | MEDIUM | همه معاملات در یک رژیم |

### اجرا

```powershell
python -m fxars research-gate <run_id>
python -m fxars research-gate <run_id> --strict   # خروج ۲ در صورت رد
```

معادل API: `GET /api/v1/governance/acceptance/{run_id}`.

### تعریف برنده‌شدن

«برنده» یعنی **عبور از این دروازه روی OOS**؛ نه بهترین بازده در نمونه. نتیجه‌ای که فقط با تغییر پارامتر پس از دیدن Locked Test بهتر شده باشد، رد می‌شود.

## ۸. اجرای نمونه

```powershell
python -m fxars backtest --instrument EURUSD --timeframe H1 --segment TRAIN --report
python -m fxars walkforward --instrument EURUSD --timeframe H1
python -m fxars pbo --instrument EURUSD --timeframe H1
python -m fxars research-gate <run_id> --strict
```
