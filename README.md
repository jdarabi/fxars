## خلاصه قابلیت‌ها

| حوزه | پیاده‌سازی |
|---|---|
| داده بازار | قرارداد Candle، اعتبارسنجی OHLC/زمان/اسپرد، قرنطینه، نسخه‌بندی اصلاحات، Raw append-only، گزارش کیفیت |
| تقویم | سشن‌های جهانی با DST، تعطیلات، کندل‌های مورد انتظار، تازگی داده متناسب با تعطیلی |
| تحلیل | Swing، BOS/CHoCH، FVG، Order Block، Liquidity Sweep، Displacement، روند/مومنتوم/نوسان/حجم، سطوح کلیدی، بنیادی، بین‌بازاری |
| شواهد | قرارداد Evidence با observed_at/available_at، ابطال، انقضا، پارامتر‌هش |
| تصمیم | تجمیع خانواده‌ای با سقف سهم، کنترل تعارض/پوشش/پایداری، NO TRADE صریح |
| سناریو | ماشین حالت DRAFT→WATCH→ARMED→TRIGGERED، ابطال/انقضا/رد، Transition ثبت‌شده |
| ریسک | اندازه موقعیت Decimal، ۲۰+ کنترل، RiskDecision، Kill Switch سراسری |
| پژوهش | بک‌تست رویدادمحور با اسپرد/کمیسیون/سوآپ/لغزش، OOS سه‌بخشی + Embargo، Walk-forward، PBO، DSR، Monte Carlo، **Purged K-Fold**, **Triple Barrier**, **Regime Detection**, **Calibration** |
| **Regime Filter** | **+۱۴۴٪ سود خالص** با فیلتر `TRENDING_UP+DOWN` روی دمو (۶۶.۹ → ۱۶۳.۵) |
| API/UI | API نسخه‌دار `/api/v1` با RBAC، Idempotency، Rate Limit، Metrics، Health/Ready/Live، داشبورد فارسی RTL |
| ممیزی | Audit زنجیره‌هش فقط‌افزودنی + Transactional Outbox |
| اجرا (MVP-2) | PaperBroker با fault injection (reject/timeout/partial)، Reconciliation، Phase Guard |
| زیرساخت | Migration framework (up/down/history)، Storage Protocol (SQLite + InMemory + Postgres-ready)، Structured logging با redaction |
| آزمون | **۳۳۸ تست** (unit + property + HTTP + security + acceptance) |

## نتایج کلیدی (دمو EURUSD/H1)

| سناریو | Baseline | Filtered (TRENDING) | تغییر |
|---|---|---|---|
| تعداد معاملات | ۳۴۷ | ۳۰۳ | −۱۲.۷٪ |
| **سود خالص** | **+۶۶.۹۲** | **+۱۶۳.۴۶** | **+۱۴۴٪** |
| Sharpe | ۰.۴۰ | **۱.۱۲** | +۱۸۲٪ |
| Calmar | ۰.۶۲ | **۱.۶۱** | +۱۶۰٪ |
| DSR | ۰.۶۳ | **۰.۸۱** | +۲۹٪ |

> این نتایج خروجی یک baseline روی داده شبیه‌سازی‌شده است و مبنای تصمیم سرمایه‌گذاری نیست.