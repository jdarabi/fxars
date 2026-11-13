## خلاصه قابلیت‌ها

| حوزه | پیاده‌سازی |
|---|---|
| داده بازار | قرارداد Candle، اعتبارسنجی OHLC/زمان/اسپرد، قرنطینه، نسخه‌بندی اصلاحات، Raw append-only، گزارش کیفیت |
| تقویم | سشن‌های جهانی با DST، تعطیلات، کندل‌های مورد انتظار، تازگی داده متناسب با تعطیلی |
| تحلیل | Swing، BOS/CHoCH، FVG، Order Block، Liquidity Sweep، Displacement، روند/مومنتوم/نوسان/حجم، سطوح کلیدی، بنیادی، بین‌بازاری |
| شواهد | قرارداد Evidence با observed_at/available_at، ابطال، انقضا، پارامتر‌هش |
| تصمیم | تجمیع خانواده‌ای با سقف سهم، کنترل تعارض/پوشش/پایداری، NO TRADE صریح، **Data Trust Score**، **گراف شواهد**، **امتیاز ترکیبی** و **بودجه عدم‌قطعیت** |
| سناریو | ماشین حالت DRAFT→WATCH→ARMED→TRIGGERED، ابطال/انقضا/رد، Transition ثبت‌شده |
| ریسک | اندازه موقعیت Decimal با هزینه، ۲۵+ کنترل شامل زیان هفتگی و سشن، RiskDecision، **قفل ریسک** و **Kill Switch سه‌سطحی** |
| پژوهش | بک‌تست رویدادمحور با اسپرد/کمیسیون/سوآپ/لغزش، OOS سه‌بخشی + Embargo، Walk-forward، PBO، DSR، Monte Carlo، **Purged K-Fold**, **Triple Barrier**, **Regime Detection**, **Calibration**، **دروازه پذیرش عددی** |
| **Regime Filter** | **+۱۴۴٪ سود خالص** با فیلتر `TRENDING_UP+DOWN` روی دمو (۶۶.۹ → ۱۶۳.۵) |
| حاکمیت | **Decision Provenance زنجیره‌ای**، **Policy Registry**، **Model Card/Tier 0–3**، Drift، Audit زنجیره‌ای |
| هوشمندی تصمیم | **Decision Journal**، **Counterfactual Replay**، **Pre-mortem**، **Scenario Heatmap**، **Challenge Mode** |
| API/UI | API نسخه‌دار `/api/v1` با RBAC، Idempotency، Rate Limit، Metrics، Health/Ready/Live، داشبورد فارسی RTL با تب «هوشمندی تصمیم» |
| ممیزی | Audit زنجیره‌هش فقط‌افزودنی + Transactional Outbox |
| اجرا (دمو/Paper) | PaperBroker با fault injection (reject/timeout/partial)، Reconciliation، Phase Guard، Forward Test |
| تجاری (فاز ۷) | چندمستاجری سطری، پلن/سهمیه اشتراک، خروجی حقوق داده، ممیزی امنیت (`security-audit`) |
| زیرساخت | Migration framework (up/down/history)، Storage Protocol (SQLite + InMemory + Postgres)، Structured logging با redaction |
| آزمون | **781 آزمون** (unit + property + HTTP + security + acceptance + governance) — 7 skip محیطی |

## نتایج کلیدی (دمو EURUSD/H1)

| سناریو | Baseline | Filtered (TRENDING) | تغییر |
|---|---|---|---|
| تعداد معاملات | ۳۴۷ | ۳۰۳ | −۱۲.۷٪ |
| **سود خالص** | **+۶۶.۹۲** | **+۱۶۳.۴۶** | **+۱۴۴٪** |
| Sharpe | ۰.۴۰ | **۱.۱۲** | +۱۸۲٪ |
| Calmar | ۰.۶۲ | **۱.۶۱** | +۱۶۰٪ |
| DSR | ۰.۶۳ | **۰.۸۱** | +۲۹٪ |

> ⚠️ **هشدار:** این جدول فقط مقایسهٔ نسبی «فیلتر رژیم» روی **داده شبیه‌سازی‌شده** است و هیچ ادعایی دربارهٔ عملکرد واقعی یا آینده ندارد. اعداد مطلق به سرمایهٔ اولیه، ریسک هر معامله و هزینه‌های فرضی حساس‌اند؛ این خروجی‌ها با پیکربندی قدیمی (ریسک ۴٪) تولید شده‌اند و با پیکربندی محافظه‌کارانهٔ فعلی (`0.0025`) بازتولید نمی‌شوند. برای تصمیم سرمایه‌گذاری از نتایج forward test روی داده واقعی استفاده کنید، نه این جدول.
## پیاده‌سازی سند تکمیلی ۱.۱

قابلیت‌های تکمیلی تصمیم و حاکمیت در نسخه ۱.۸ پیاده‌سازی شده است: Data Trust Score، گراف شواهد، امتیاز ترکیبی، بودجه عدم‌قطعیت، Decision Provenance، Policy/Model Registry، قفل ریسک، Kill Switch سه‌سطحی، ژورنال/بازپخش/پیش‌مرگ/نقشه حرارتی/چالش و دروازه پذیرش پژوهش.

- ماتریس ردیابی: `docs/SUPPLEMENT_V1_1.md`
- دامنه و معیارهای خروج: `docs/MVP.md`
- سیاست ریسک و قفل: `docs/RISK_POLICY.md`
- قراردادها و Provenance: `docs/DATA_CONTRACTS.md`
- پروتکل پذیرش: `docs/VALIDATION_PROTOCOL.md`

```powershell
python -m fxars serve                # API + داشبورد (تب هوشمندی تصمیم)
python -m fxars research-gate <run_id> --strict
python -m unittest                   # کل آزمون‌ها
```
