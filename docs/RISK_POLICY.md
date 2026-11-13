# سیاست ریسک و دروازه ایمنی

## ۱. اندازه موقعیت

```
risk_amount      = equity × risk_per_trade
pip_value_lot    = pip_size × contract_size × quote_to_account_rate
loss_per_lot     = (stop_distance / pip_size) × pip_value_lot + commission_per_lot
raw_volume       = risk_amount / loss_per_lot
volume           = floor(raw_volume, lot_step)   # فقط مضرب مجاز
```

قواعد:
- همه محاسبات با `Decimal`؛ گرد کردن حجم رو به پایین.
- ارز مظنه ≠ ارز حساب ⇒ نرخ تبدیل و `quote_to_account_rate` صریح و قابل ردیابی.
- حجم کمتر از `min_lot` ⇒ رد (`BELOW_MIN_LOT`)، نه گرد کردن رو به بالا.
- کمیسیون در زیان هر لات لحاظ می‌شود تا ریسک واقعی بیش‌برآورد نشود.

## ۲. کنترل‌های اجباری (RiskDecision)

| کنترل | کد | قاعده |
|---|---|---|
| نسخه سیاست | policy_present | policy_version موجود |
| Kill Switch | kill_switch_inactive | هیچ سطح SYSTEM/MODULE/ACCOUNT فعال نباشد |
| قفل ریسک | risk_lock_clear | وضعیت قفل مسدودکننده نباشد |
| اعتبار سناریو | scenario_valid | جهت/ورود/حد ضرر/انقضا/وضعیت مجاز |
| قدرت سیگنال | signal_strength | ≥ `min_signal_strength` |
| مشخصات نماد | instrument_spec_valid | معتبر و در تاریخ اعتبار |
| تازگی حساب | account_snapshot_fresh | ≤ ۳۰۰ ثانیه |
| تازگی داده | data_fresh | مطابق تقویم سشن |
| سشن بازار | market_open | بازار باز است یا حداکثر `data_grace_seconds` از آخرین بازبودن گذشته |
| قیمت | price_valid | جهت صحیح Stop/Entry |
| فاصله حد ضرر | stop_distance_within_limits | ۳ تا ۱۵۰ پیپ |
| حجم | position_size_valid | ≥ min_lot و مضرب lot_step |
| ریسک هر معامله | risk_per_trade_within_limit | ≤ سقف سخت ۰٫۵٪ |
| زیان روزانه | daily_loss_within_limit | پیش‌فرض ۲٪ |
| زیان هفتگی | weekly_loss_within_limit | ۳× سقف زیان روزانه (حداکثر ۱۰۰٪) |
| افت سرمایه | drawdown_within_limit | توقف ۱۰٪ (هشدار ۵٪) |
| تعداد باز | max_open_trades_ok | کل ۳، هر نماد ۱ |
| مواجهه ارزی | currency_exposure_ok | ۲٪ Equity (بر مبنای مارجین) |
| خوشه هم‌بسته | correlation_exposure_ok | ۲٫۵٪ Equity |
| Blackout خبری | event_blackout_ok | ±۳۰ دقیقه رویداد HIGH |
| اسپرد | spread_within_limit | ≤ ۳ پیپ |
| مارجین | margin_sufficient | با بافر ۲۰٪ |
| پنجره اعتبار | validity_window_ok | قبل از انقضا |

پیش‌فرض‌ها **نقطه شروع طراحی** هستند و باید با تصویب مالک ریسک تثبیت شوند (بخش ۹-۲ سند).

## ۳. خروجی

`approved = همه کنترل‌ها pass`. `reason_code` اولین کنترل ردشده، `reason_detail` خلاصه دلایل، `valid_until = now + TTL (۳۰۰s)` و `inputs_hash` برای بازتولید.

## ۴. Kill Switch سه‌سطحی

- سه سطح: `SYSTEM` (کل سامانه)، `MODULE:<name>` (ماژول تحلیل/اجرا/نماد) و `ACCOUNT:<id>` (حساب).
- وضعیت در `system_state` ذخیره و در سرویس ریسک و اجرا enforce می‌شود؛ نه فقط UI.
- `is_active()` بدون آرگومان اگر هر سطحی فعال باشد `True` است (Fail-Safe). بررسی دقیق با `scope`/`target`.
- فعال/غیرفعال‌سازی با نقش مجاز (`killswitch.toggle`)، دلیل اجباری، ثبت Audit و Outbox.
- فعال بودن هر سطح ⇒ RiskDecision رد (`KILL_SWITCH_ACTIVE`) و OrderIntent ممنوع.
- غیرفعال‌سازی محدودیت‌های ریسک را دور نمی‌زند؛ کنترل‌ها مستقل باقی می‌مانند.

## ۵. قفل ریسک (Risk Lock)

چرخه: `NORMAL → WARNING → LOCKED_DAILY → LOCKED_WEEKLY → KILL_SWITCH → MANUAL_REVIEW`.

| وضعیت | معنا | ارسال سفارش |
|---|---|---|
| NORMAL | عادی | مجاز |
| WARNING | عبور از آستانه هشدار زیان/افت سرمایه | مجاز با هشدار |
| LOCKED_DAILY | زیان روزانه ≥ سقف یا افت سرمایه ≥ حد توقف | ممنوع |
| LOCKED_WEEKLY | زیان هفتگی ≥ ۳× سقف روزانه | ممنوع |
| KILL_SWITCH | Kill Switch فعال | ممنوع |
| MANUAL_REVIEW | بازبینی دستی ریسک | ممنوع |

- `RiskService` پیش از دروازه، زیان روزانه را از `AccountSnapshot.daily_pnl` و زیان هفتگی محقق‌شده را از `closed_trades` ابتدای هفته سشن محاسبه و ماشین قفل را به‌روز می‌کند.
- قفل‌های `LOCKED_*`، `KILL_SWITCH` و `MANUAL_REVIEW` خودکار باز نمی‌شوند؛ آزادسازی فقط با دلیل از `POST /api/v1/risk/lock` و نقش مجاز.
- هر گذار با اکشن ممیزی `RISK_LOCK_CHANGED` و تاریخچه ۲۰ رخداد آخر در UI ثبت می‌شود.

## ۶. عدم دور زدن

- `RiskGate` تنها راه تولید RiskDecision است.
- `ExecutionService.create_intent` وجود RiskDecision تأییدشده و منقضی‌نشده + Kill Switch غیرفعال + قفل ریسک باز + فاز مجاز را الزامی می‌کند.
- در MVP-1 (`READ_ONLY`) هر تلاش ساخت OrderIntent با `PHASE_VIOLATION` رد و در Audit ثبت می‌شود.
- آزمون‌های `tests/test_risk.py`، `tests/test_risk_lock.py` و `tests/test_execution.py` این مسیرها را پوشش می‌دهند.

## ۷. هزینه‌ها در اندازه موقعیت

- کمیسیون هر لات در `loss_per_lot` لحاظ می‌شود تا ریسک واقعی بیش‌برآورد نشود.
- اسپرد با کنترل `spread_within_limit` و لغزش در مدل بک‌تست لحاظ می‌شود؛ حجم رو به پایین گرد می‌شود.
- هیچ هزینه‌ای به‌صورت پیش‌فرض صفر در نظر گرفته نمی‌شود؛ صفر بودن کل هزینه‌ها در بک‌تست، ضدالگوی `IGNORED_COSTS` است.
