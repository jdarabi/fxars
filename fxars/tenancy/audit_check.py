"""ممیزی امنیت و حقوق داده (دروازه فاز ۷).

فقط خواندنی است: تنظیمات، ستون‌های tenant_id، زنجیره ممیزی، نشت اسرار در
payloadهای ممیزی و دسترس‌پذیری گزارش حقوق داده را بررسی می‌کند و نتیجه را
به‌صورت فهرست check برمی‌گرداند.
"""

from __future__ import annotations

from typing import Any

from fxars.audit.audit import AuditAction
from fxars.core.errors import FxarsError
from fxars.domain.enums import Role

TENANT_TABLES = ("users", "analysis_runs", "scenarios", "risk_decisions", "order_intents")
_SENSITIVE_PARTS = ("password", "passwd", "token", "secret", "api_key", "apikey", "authorization")
_INSECURE_KEYS = {"dev-insecure-secret-change-me", "", "change-me", "secret"}
_REQUIRED_AUDIT_ACTIONS = (
    AuditAction.USER_LOGIN,
    AuditAction.USER_LOGIN_FAILED,
    AuditAction.ACCESS_DENIED,
    AuditAction.CONFIG_CHANGED,
    AuditAction.KILL_SWITCH_CHANGED,
    AuditAction.SCENARIO_TRANSITION,
    AuditAction.RISK_EVALUATED,
)


def _check(check_id: str, title: str, status: str, detail: str) -> dict[str, str]:
    return {"id": check_id, "title": title, "status": status, "detail": detail}


def _sensitive_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{path}.{key}" if path else str(key)
            if any(part in str(key).lower() for part in _SENSITIVE_PARTS):
                found.append(name)
            found.extend(_sensitive_keys(item, name))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_sensitive_keys(item, f"{path}[{index}]"))
    return found


def run_security_audit(platform, *, tenant_id: str = "default") -> dict[str, Any]:
    settings = platform.settings
    checks: list[dict[str, str]] = []

    mfa_roles = set(settings.security.mfa_roles)
    required_roles = {Role.ADMIN, Role.RISK_MANAGER, Role.OPERATOR}
    missing_roles = sorted(role.value for role in required_roles - mfa_roles)
    checks.append(_check(
        "mfa_roles",
        "الزام MFA برای نقش‌های حساس",
        "fail" if missing_roles else "pass",
        f"نقش‌های بدون MFA: {', '.join(missing_roles)}" if missing_roles
        else "ADMIN/RISK_MANAGER/OPERATOR همگی MFA دارند.",
    ))

    ttl = settings.api.session_ttl_minutes
    checks.append(_check(
        "session_ttl",
        "عمر نشست",
        "pass" if 0 < ttl <= 1440 else "fail",
        f"session_ttl_minutes={ttl} (بازه مجاز 1..1440)",
    ))

    rate = settings.api.rate_limit_per_minute
    checks.append(_check(
        "rate_limit",
        "محدودیت نرخ درخواست",
        "pass" if 0 < rate <= 600 else "warn",
        f"rate_limit_per_minute={rate} (سقف پیشنهادی 600)",
    ))

    key = settings.security.secret_key
    key_ok = key not in _INSECURE_KEYS and len(key) >= 32
    if key_ok:
        key_status = "pass"
    elif settings.environment == "prod":
        key_status = "fail"
    else:
        key_status = "warn"
    checks.append(_check(
        "secret_key",
        "کلید امنیتی نشست",
        key_status,
        f"طول کلید={len(key)} (محیط {settings.environment})" if key else "کلید تنظیم نشده است.",
    ))

    iterations = settings.security.pbkdf2_iterations
    checks.append(_check(
        "password_hashing",
        "قدرت هش رمز عبور",
        "pass" if iterations >= 200_000 else "fail",
        f"pbkdf2_iterations={iterations} (حداقل 200000)",
    ))

    tenant_issues: list[str] = []
    for table in TENANT_TABLES:
        try:
            total = int(platform.db.scalar(f"SELECT COUNT(*) FROM {table}") or 0)
            orphan = int(platform.db.scalar(
                f"SELECT COUNT(*) FROM {table} WHERE tenant_id IS NULL OR tenant_id = ''"
            ) or 0)
        except Exception as exc:  # ستون یا جدول در نسخه قدیمی schema
            tenant_issues.append(f"{table}: ستون tenant_id در دسترس نیست ({type(exc).__name__})")
            continue
        if orphan:
            tenant_issues.append(f"{table}: {orphan} ردیف بدون tenant_id")
        elif total == 0:
            tenant_issues.append(f"{table}: خالی (پوشش قابل سنجش نیست)")
    checks.append(_check(
        "tenant_columns",
        "جداسازی سطری tenant_id",
        "fail" if any("tenant_id" in issue for issue in tenant_issues) else "pass",
        "; ".join(tenant_issues) if tenant_issues else "همه جدول‌ها ستون tenant_id دارند و ردیف بی‌مستاجر نیست.",
    ))

    chain = platform.audit.verify()
    checks.append(_check(
        "audit_chain",
        "صحت زنجیره ممیزی",
        "pass" if chain.get("valid") else "fail",
        f"valid={chain.get('valid')} count={chain.get('count')} broken_seq={chain.get('broken_seq')}",
    ))

    actions = {getattr(AuditAction, name) for name in dir(AuditAction) if name.isupper()}
    missing_actions = [action for action in _REQUIRED_AUDIT_ACTIONS if action not in actions]
    checks.append(_check(
        "audit_coverage",
        "پوشش رخدادهای حساس در ممیزی",
        "pass" if not missing_actions else "fail",
        f"رخدادهای غایب: {', '.join(missing_actions)}" if missing_actions
        else "ورود/دسترسی/پیکربندی/ریسک/گذار سناریو ممیزی می‌شوند.",
    ))

    leaked: list[str] = []
    for entry in platform.audit.list_entries(limit=200):
        leaked.extend(_sensitive_keys(entry.payload))
    checks.append(_check(
        "audit_no_secrets",
        "نبود اسرار در payload ممیزی",
        "fail" if leaked else "pass",
        f"کلیدهای حساس: {', '.join(sorted(set(leaked))[:10])}" if leaked
        else "در ۲۰۰ رکورد اخیر کلید حساس یافت نشد.",
    ))

    try:
        rights = platform.data_rights.retention_report(tenant_id)
        policies = rights.get("policies") or rights.get("policy") or {}
        rights_ok = bool(policies) and "counts" in rights
        rights_detail = (
            f"مستاجر {tenant_id}: {len(policies)} سیاست نگهداری، counts موجود={'counts' in rights}"
        )
    except FxarsError as exc:
        rights_ok = False
        rights_detail = f"{exc.code}: {exc.message}"
    checks.append(_check(
        "data_rights",
        "گزارش حقوق داده و نگهداری",
        "pass" if rights_ok else "fail",
        rights_detail,
    ))

    passed = sum(1 for item in checks if item["status"] == "pass")
    failed = sum(1 for item in checks if item["status"] == "fail")
    warned = sum(1 for item in checks if item["status"] == "warn")
    return {
        "checks": checks,
        "ok": failed == 0,
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "score": round(passed / len(checks), 3) if checks else 0.0,
    }
