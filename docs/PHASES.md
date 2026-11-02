# نقشه راه و دروازه‌های فاز

| فاز | دامنه | وضعیت در این تحویل | دروازه عبور |
|---|---|---|---|
| MVP-1 Read-only | داده، کیفیت، تحلیل، سناریو، Risk Gate بدون سفارش، بک‌تست، داشبورد | ✅ **پیاده‌سازی کامل** (۳۳۸ تست) | AC-01..AC-12 ✅ |
| MVP-2 Paper/Demo | اتصال آزمایشی، Order State Machine، Idempotency، تطبیق | 🟡 **در حال انجام** (P6-1 کامل) | Forward test، تطبیق، قطع اتصال |
| MVP-3 اجرای محدود | Assisted سپس Automated محدود، سقف سخت | ⏳ قرارداد و مدل داده | تصویب ریسک، OOS، امنیت |
| MVP-4 تجاری | چندکاربره، Tenant Isolation، اشتراک | ⏳ خارج از دامنه | ممیزی امنیت/حقوق داده |

## دروازه‌های تصمیم (Gate A..G)

- **A — تصویب طراحی:** دامنه، نماد پایلوت، منبع داده، قراردادها، Acceptance. ✅
- **B — آمادگی داده:** کیفیت، تازگی، Lineage، بازتولید. ✅
- **C — آمادگی تحلیل:** تعریف/نسخه/آزمون الگوریتم‌ها. ✅
- **D — آمادگی پژوهش:** پروتکل OOS، هزینه‌ها، گزارش بازتولیدپذیر. ✅
- **E — آمادگی Demo:** State machine، Idempotency، Reconciliation، Fault test. 🟡 (P6-1 کامل، P6-2/3 در جریان)
- **F — آمادگی اجرای واقعی:** ریسک، امنیت، Forward test، Kill Switch، تأیید رسمی. ⏳
- **G — تجاری‌سازی:** حقوق داده، Tenant isolation، پشتیبانی، انطباق. ⏳

## قواعد فاز

1. قابلیت فاز بعد در فاز قبل «ناقص» فعال نمی‌شود؛ مدل داده می‌تواند آماده باشد.
2. هر تغییر مؤثر بر منطق معاملاتی/ریسک/داده نیازمند شناسه تغییر، نسخه و آزمون رگرسیون است.
3. فعال‌سازی هر فاز فقط با مدرک مستند عبور از دروازه مربوطه.

## وضعیت فعلی (v1.4.1)

- فاز پیش‌فرض: `READ_ONLY`.
- `ExecutionService` در READ_ONLY هر تلاش ساخت OrderIntent را با `PHASE_VIOLATION` رد و Audit می‌کند.
- `PaperBroker` با fault injection آماده است (P6-1).
- `ReconciliationService` آماده است (P6-1).
- ۳۳۸ تست سبز (۱۸۸ → ۳۳۸ در این جلسات).

## پیشرفت این جلسه (P5-3 → P6-1)

| بسته | وضعیت |
|---|---|
| P4-1: Storage Protocol | ✅ |
| P4-2: Migration Framework | ✅ |
| P5-3: Structured Logging | ✅ |
| P6-1: PaperBroker + Reconciliation | ✅ |

## گام بعدی

- **P6-2:** Phase Guard E2E (تست کامل `READ_ONLY → PAPER`)
- **P6-3:** Reconciliation CLI (`reconcile`, `orders list --status UNKNOWN`)
- **P4-3:** Postgres adapter skeleton