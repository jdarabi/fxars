# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.11.x   | :white_check_mark: |
| < 1.11   | :x:                |

## Reporting a Vulnerability

**Do NOT open a public issue for security vulnerabilities.**

Instead, report privately to: security@example.com (replace with real address).

Please include:
- Affected version (python -m fxars --version)
- Minimal reproduction steps
- Impact assessment

You can expect an acknowledgment within 72 hours.

## Security-Relevant Design

- **Phase Guard:** In READ_ONLY, no order path is reachable (AC-05).
- **Kill Switch:** Enforced in RiskService and ExecutionService, not only UI.
- **RBAC:** Server-side, matrix in `fxars/identity/rbac.py`; `tenant.admin` برای مدیریت مستاجران.
- **MFA:** ADMIN / RISK_MANAGER / OPERATOR بدون کد TOTP نمی‌توانند وارد شوند.
- **Tenant isolation:** `tenant_id` در کاربران، تحلیل‌ها، سناریوها، تصمیم‌های ریسک و سفارش‌ها؛ دسترسی سطری در Repository/API/Service اعمال می‌شود، مستاجر دیگر 404 و مستاجر غیرفعال 403 است.
- **Subscription quotas:** پلن `basic`/`pro`/`enterprise` در مرز سرویس اعمال می‌شود و عبور از سقف `QUOTA_EXCEEDED` (429) است.
- **Data rights:** `GET /api/v1/tenant/export` خروجی بدون هش رمز/TOTP/توکن/secret می‌دهد؛ `GET /api/v1/tenant/retention` سیاست نگهداری را گزارش می‌کند. حذف دسته‌ای مستاجر بدون تأیید صریح اپراتور و پشتیبان انجام نمی‌شود.
- **Secrets:** Never stored in repo; `.env` is gitignored. TOTP secrets encrypted with SecretBox. محیط `prod` با کلید پیش‌فرض/کوتاه بالا نمی‌آید.
- **KMS:** کلید اسرار و امضای ممیزی از `fxars/security/kms.py` می‌آید. `security.kms_provider=local` کلید را از `secret_key` مشتق می‌کند (توسعه/تک‌نمونه)؛ `kms_provider=env` کلید ۳۲+ بایتی را از `FXARS_KMS_MASTER_KEY` (hex/base64) و کلید قبلی را برای چرخش از `FXARS_KMS_MASTER_KEY_PREVIOUS` می‌خواند. هیچ کلیدی لاگ نمی‌شود و `KeyMaterial` مقدار کلید را در repr نشان نمی‌دهد.
- **Audit anchor:** `python -m fxars.cli.main audit-anchor --out <file>` سر زنجیره را با کلید کاربرد `audit-anchor` امضا می‌کند و `audit-verify-anchor --file <file>` امضا و تطابق head/count را بررسی می‌کند. فایل لنگر باید بیرون از پایگاه داده (WORM/offsite) نگهداری شود تا کوتاه‌سازی کل زنجیره آشکار شود.
- **Demo mode:** مسیرهای دمو (شامل `demo-totp`) فقط با `FXARS_ENABLE_DEMO=1`، محیط `dev` و اتصال localhost فعال‌اند؛ مقداردهی `FXARS_ENABLE_DEMO=1` در محیط غیر‌dev در startup خطا می‌دهد. هیچ رمز دمو در کد/UI ذخیره نمی‌شود: `bootstrap` در نبود متغیر محیطی رمز تصادفی می‌سازد و یک‌بار چاپ می‌کند؛ برای انتخاب رمز از `FXARS_ADMIN_PASSWORD`/`FXARS_ANALYST_PASSWORD` استفاده کنید و اسکریپت عیب‌یابی آن را از `FXARS_DEMO_PASSWORD` می‌خواند.
- **Backup/cache hygiene:** مقادیر رمز دموی قدیمی در نسخه‌های پشتیبان/کش (`.fix-backups/`، `.cleanup-backups/`، `.hypothesis/constants/`) در ۲۰۲۶-۱۱-۱۱ با placeholder جایگزین شدند (۴۸ فایل، ۱۰۹ رخداد) و با اسکن هش‌محور تأیید شد که رخدادی باقی نمانده است. مقادیر رمز در گزارش‌ها چاپ نمی‌شوند و فقط مسیر/تعداد/طول گزارش می‌شود.
- **Audit:** Append-only hash chain with SQLite triggers.
- **Idempotency:** Atomic state machine (pending/completed/failed).

## Security & Data-Rights Audit

```bash
python -m fxars.cli.main security-audit --tenant default
```

بررسی‌ها: MFA نقش‌های حساس، TTL نشست، محدودیت نرخ، کیفیت کلید امنیتی (بدون چاپ مقدار)، قدرت هش رمز، وجود `tenant_id` و نبود ردیف بی‌مستاجر، صحت زنجیره ممیزی، پوشش رخدادهای حساس، نبود کلید حساس در payload ممیزی، و دسترس‌پذیری گزارش حقوق داده. خروجی JSON با `--json` و کد خروج غیرصفر در صورت `fail`.


## Known Limitations

See docs/LIMITATIONS.md for the full list. Notable security-relevant items:

- Audit hash-chain is not digitally signed; an attacker with DB write access can rebuild the chain. The external HMAC anchor detects this only if the anchor file is stored outside the database (WORM/offsite). For non-repudiation, plug an asymmetric KMS/HSM signer behind `KeyProvider`.
- Rate limiter is in-process by default; use Redis backend for multi-instance.
- SecretBox uses HMAC-CTR with a KMS-derived key and versioned ciphertext (`v2:<key_id>:...`); legacy ciphertexts stay readable via the legacy key. Remaining work: a managed-cloud/HSM adapter and per-tenant key isolation (the current provider derives per-purpose keys from one master).

## Disclosure Policy

We follow coordinated disclosure: 90 days or until a fix is released,
whichever comes first.