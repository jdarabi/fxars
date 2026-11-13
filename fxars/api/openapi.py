"""قرارداد OpenAPI نسخه‌دار (بدون وابستگی به FastAPI)."""

from __future__ import annotations

from typing import Any

from fxars.version import CODE_VERSION, CONTRACT_VERSION, DOCUMENT_ID


def openapi_spec(server_url: str = "http://127.0.0.1:8080") -> dict[str, Any]:
    error_schema = {
        "type": "object",
        "properties": {
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "details": {"type": "object"},
                },
            }
        },
    }
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "FX-ARS API",
            "version": CONTRACT_VERSION,
            "description": f"سامانه تحلیل و پشتیبانی تصمیم فارکس — سند مبنا {DOCUMENT_ID} — نسخه کد {CODE_VERSION}",
        },
        "servers": [{"url": server_url}],
        "components": {
            "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
            "schemas": {"Error": error_schema},
        },
        "security": [{"bearerAuth": []}],
        "paths": {
            "/api/v1/health": {"get": {"summary": "سلامت سرویس", "security": [], "responses": {"200": {"description": "OK"}}}},
            "/api/v1/auth/login": {"post": {"summary": "ورود و دریافت توکن", "security": [], "responses": {"200": {"description": "OK"}}}},
            "/api/v1/auth/logout": {"post": {"summary": "خروج", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/auth/me": {"get": {"summary": "کاربر جاری", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/tenant": {"get": {"summary": "پلن، سقف و مصرف مستاجر جاری", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/tenant/export": {"get": {"summary": "خروجی داده مستاجر جاری (بدون اسرار)", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/tenant/retention": {"get": {"summary": "سیاست نگهداری و حجم داده مستاجر جاری", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/tenants": {"get": {"summary": "فهرست مستاجران (مدیر)", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/tenants/{tenant_id}": {"post": {"summary": "تغییر پلن/سهمیه مستاجر (مدیر)", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/tenants/{tenant_id}/export": {"get": {"summary": "خروجی داده مستاجر (مدیر)", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/tenants/{tenant_id}/retention": {"get": {"summary": "گزارش نگهداری مستاجر (مدیر)", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/meta": {"get": {"summary": "نسخه‌ها، فاز و پیکربندی", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/instruments": {"get": {"summary": "فهرست نمادها", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/market-data/candles": {"get": {"summary": "کندل‌ها", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/data-quality/runs": {"get": {"summary": "گزارش کیفیت داده", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/analysis-runs": {
                "get": {"summary": "فهرست اجراهای تحلیل", "responses": {"200": {"description": "OK"}}},
                "post": {"summary": "اجرای تحلیل با config نسخه‌دار", "responses": {"200": {"description": "OK"}}},
            },
            "/api/v1/analysis-runs/{run_id}": {"get": {"summary": "نتیجه تحلیل و شواهد", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/scenarios": {"get": {"summary": "فهرست سناریوها", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/scenarios/{scenario_id}": {"get": {"summary": "جزئیات سناریو", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/scenarios/{scenario_id}/evaluate": {"post": {"summary": "ارزیابی شرط‌های سناریو", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/scenarios/{scenario_id}/transition": {"post": {"summary": "گذار دستی مجاز", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/risk/evaluate": {"post": {"summary": "ارزیابی ریسک (بدون ارسال سفارش)", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/risk/decisions": {"get": {"summary": "فهرست تصمیم‌های ریسک", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/risk/decisions/{decision_id}": {"get": {"summary": "جزئیات تصمیم ریسک", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/backtests": {
                "get": {"summary": "فهرست بک‌تست‌ها", "responses": {"200": {"description": "OK"}}},
                "post": {"summary": "ایجاد بک‌تست", "responses": {"200": {"description": "OK"}}},
            },
            "/api/v1/backtests/{run_id}": {"get": {"summary": "جزئیات بک‌تست", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/audit-events": {"get": {"summary": "گزارش ممیزی", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/killswitch": {
                "get": {"summary": "وضعیت Kill Switch", "responses": {"200": {"description": "OK"}}},
                "post": {"summary": "فعال/غیرفعال کردن Kill Switch", "responses": {"200": {"description": "OK"}}},
            },
        },
    }


def docs_html() -> str:
    return """<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>FX-ARS API Docs</title>
<style>body{font-family:Tahoma,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px}
code{background:#1e293b;padding:2px 6px;border-radius:6px}a{color:#7dd3fc}</style></head>
<body><h1>مستندات API — FX-ARS</h1>
<p>قرارداد OpenAPI در <a href="/openapi.json">/openapi.json</a> در دسترس است.</p>
<p>احراز هویت: <code>Authorization: Bearer &lt;token&gt;</code> — دریافت توکن از <code>POST /api/v1/auth/login</code>.</p>
<p>همه خطاها با ساختار <code>{error:{code,message,correlation_id,details}}</code> برگردانده می‌شوند.</p>
</body></html>"""
