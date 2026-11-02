# الگوریتم‌ها و مشخصات ماژول‌ها

هر ماژول مستقل، خاموش/روشن‌پذیر و دارای نسخه است. مشخصات کامل در `fxars/analysis/modules.py` و از طریق `GET /api/v1/meta` قابل دریافت است.

## ۱. اندیکاتورها (علّی و بدون نگاه به آینده)

- SMA/EMA (۲۰/۵۰/۲۰۰)، RSI ویلدر (۱۴)، ROC(۱۰)، ATR ویلدر (۱۴)
- نوسان تحقق‌یافته (انحراف معیار بازده ۲۰ و ۸۰ کندل)
- صدک ATR در پنجره ۱۰۰ کندل
- همه سری‌ها هم‌طول کندل‌ها با `None` در Warm-up

## ۲. ساختار بازار (`structure.*`)

- **Swing High/Low:** `High[i] > High[i-k..i-1]` و `High[i] ≥ High[i+1..i+k]` (قرینه برای Low). تأیید فقط در `i+k`; `available_at` همان کندل تأیید است.
- **BOS:** بسته‌شدن بالاتر از آخرین Swing High تأییدشده و شکسته‌نشده (یا پایین‌تر از Swing Low) در جهت روند.
- **CHoCH:** شکست ساختار در خلاف جهت روند فعال قبلی.
- **FVG:** `Low[i] > High[i-2]` (صعودی) یا `High[i] < Low[i-2]` (نزولی) با حداقل عرض `fvg_min_atr × ATR`.
- **Order Block:** آخرین کندل مخالف (تا ۳ کندل) پیش از بدنه `> displacement_atr × ATR` با بدنه/دامنه > ۰٫۶.
- **Liquidity Sweep:** عبور سایه از سقف/کف ۲۴ کندل و بازگشت بسته‌شدن؛ نسبت سایه ≥ ۰٫۳.
- **Displacement:** بدنه > `displacement_atr × ATR`.

شدت هر شاهد از فاصله شکست/عرض ناحیه نسبت به ATR و تأیید ساختار محاسبه و به `[0.1, 0.95]` محدود می‌شود. ابطال و انقضا برای هر شاهد ثبت می‌شود.

## ۳. روند، مومنتوم، نوسان، حجم

- **روند:** `EMA20 > EMA50 > EMA200` و شیب مثبت ⇒ LONG؛ قرینه ⇒ SHORT؛ در غیر این صورت NEUTRAL (شدت کم، از تصمیم حذف می‌شود).
- **مومنتوم:** RSI ≥ ۵۵ و ROC > ۰ ⇒ LONG؛ RSI ≤ ۴۵ و ROC < ۰ ⇒ SHORT.
- **نوسان:** صدک ATR ≥ ۸۰ «نوسان بالا»، ≤ ۲۰ «فشرده»؛ شاهد خنثی و زمینه‌ای.
- **حجم:** z-score تیک‌والیوم نسبت به ۲۰ کندل؛ جهت از بدنه. برچسب صریح: Tick Volume حجم کل بازار نیست.

## ۴. سطوح کلیدی

سقف/کف روز و هفته قبل، سطوح سشن‌های تکمیل‌شده، اعداد گرد ۵۰ پیپی و Swingهای ۵۰ کندل. سطوح نزدیک (`level_merge_pips`) ادغام و در فاصله `level_proximity_pips` شاهد با شدت محدود (≤ ۰٫۷) صادر می‌شود. تکرار شاهد برای یک سطح حداقل ۸ کندل فاصله دارد.

## ۵. بنیادی و بین‌بازاری

- **بنیادی:** غافلگیری `actual - forecast` نسبت به ارز پایه/مظنه؛ فقط رویدادهای `available_at ≤ تصمیم`؛ اهمیت رویداد در شدت اثر دارد.
- **بین‌بازاری:** همبستگی پنجره‌ای ۶۰ کندل با سری مرجع (پیش‌فرض DXY برای EURUSD/GBPUSD/XAUUSD)؛ جهت = علامت `بازده مرجع × همبستگی`؛ حداقل |همبستگی| ۰٫۳۵ و |z| ۰٫۸.

## ۶. قرارداد Evidence و تجمیع

- شواهد در خانواده‌ها: STRUCTURE، TREND، MOMENTUM، LEVELS، VOLUME، FUNDAMENTAL، INTERMARKET، VOLATILITY.
- سقف سهم هر خانواده: `family_cap × weight` (پیش‌فرض ۰٫۳۵).
- `score = Σ family_net`؛ `coverage = خانواده‌های جهت‌دار فعال / ۷`.
- `stability = توافق علامت امتیاز در سه checkpoint` (تصمیم، ۱ و ۲ کندل قبل).
- ترتیب کنترل: شاهد قابل استفاده → تعارض خانواده‌ها → پوشش → پایداری → حداقل امتیاز.
- خروجی: LONG/SHORT/NO_TRADE با دلیل، تعارض‌ها، سهم خانواده‌ها و شناسه شواهد.

## ۷. ساخت سناریو

- Trigger: عبور از `close + 0.15×ATR` (LONG) یا `close - 0.15×ATR` (SHORT) با الزام کندل بسته.
- Stop: آخرین Swing Low/High ± `stop_buffer_pips`؛ اگر فاصله کمتر از حداقل باشد تعدیل می‌شود.
- Targets: مضارب R (پیش‌فرض ۱٫۵ و ۳٫۰).
- Expiry بر مبنای **کندل‌های معاملاتی** محاسبه می‌شود (تعطیلی بازار باعث انقضای زودهنگام نمی‌شود).

## ۸. ماژول‌های آینده

ML/Deep Learning در MVP-1 خارج از دامنه است. مسیر مدل: label دقیق (Triple Barrier)، Purging/Embargo، Nested Walk-forward، کالیبراسیون (Brier/LogLoss/ECE)، Model Registry و Drift — بدون ورود به مسیر تصمیم تا عبور از Gate.

## . ریم بازار (P3-4)

ماول `fxars/research/regime.py` هر کندل را به یکی از پنج ریم نسبت میدهد:

| ریم | تعریف | اولویت |
|---|---|---|
| `LOW_VOL` | ATR percentile   (فشردگی نوسان) |  (بالاترین) |
| `TRENDING_UP` | `(ema_fast - ema_slow) / atr > 0.05` و ATR percentile بین  و  |  |
| `TRENDING_DOWN` | `(ema_fast - ema_slow) / atr < -0.05` و ATR percentile بین  و  |  |
| `HIGH_VOL` | ATR percentile   و روند واضح نیست |  |
| `RANGING` | پیشفرض |  (پایینترین) |

**پارامترها** (`RegimeConfig`):
- `ema_fast=20`, `ema_slow=50`
- `atr_period=14`, `vol_lookback=100`
- `vol_high_percentile=80.0`, `vol_low_percentile=20.0`
- `trend_slope_threshold=0.05`

**نکات پیادهسازی:**
- `atr_percentile` با **midpoint rank** محاسبه میشود تا سری ثابت ~ بدهد (نه ).
- ریم نوسان وقتی غالب میشود که ATR percentile در صدکهای حدی باشد **و** روند واضح نباشد.
- ریم روند وقتی غالب میشود که `slope_norm` از آستانه عبور کند (اولویت بالاتر از HIGH_VOL).

### فیلتر ریم در بکتست (P3-4-ext2)

`BacktestConfig.allowed_regimes: tuple[str, ...]` (پیشفرض `()` = همه مجاز).
اگر پر باشد فقط سیگنالهایی معامله میشوند که کندل جاریشان در ریمهای مجاز باشد.

**نتیجه تجربی روی EURUSD/H1 (دمو):**

| متریک | Baseline | Filtered (TRENDING_UP+DOWN) | تغییر |
|---|---|---|---|
| تعداد معاملات |  |  | . |
| سود خالص | +. | +. | **+** |
| Sharpe | . | . | **+** |
| Calmar | . | . | + |
| DSR | . | . | + |
| سیگنالهای ردشده |  |  |  |

### پیکربندی

از طریق `config/settings.json`:
```json
{"backtest": {"allowed_regimes": ["TRENDING_UP", "TRENDING_DOWN"]}}
```

از طریق CLI:
```powershell
python -m fxars backtest --instrument EURUSD --timeframe H1 --overrides "{\"allowed_regimes\": [\"TRENDING_UP\"]}"
```

از طریق API (`POST /api/v1/backtests`):
```json
{"instrument_id": "EURUSD", "timeframe": "H1", "overrides": {"allowed_regimes": ["TRENDING_UP"]}}
```

`allowed_regimes` بخشی از `config_hash` است پس هر تغییر آن خروجیهای بکتست را از نظر بازتولیدپذیری تغییر میدهد.
