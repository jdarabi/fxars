"""خطاهای دامنه با کد پایدار، پیام فارسی و نگاشت HTTP.

قرارداد خطا مطابق بخش ۱۴-۲ سند: code / message / correlation_id / details.
"""

from __future__ import annotations

from typing import Any


class FxarsError(Exception):
    """پایه همه خطاهای قابل پیش‌بینی سامانه."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    default_message: str = "خطای داخلی سامانه رخ داد."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        self.correlation_id = correlation_id
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "correlation_id": self.correlation_id,
                "details": self.details,
            }
        }


class ValidationError(FxarsError):
    code = "VALIDATION_ERROR"
    http_status = 400
    default_message = "ورودی نامعتبر است."


class AuthenticationError(FxarsError):
    code = "UNAUTHENTICATED"
    http_status = 401
    default_message = "احراز هویت لازم است."


class AuthorizationError(FxarsError):
    code = "FORBIDDEN"
    http_status = 403
    default_message = "دسترسی به این عملیات مجاز نیست."


class NotFoundError(FxarsError):
    code = "NOT_FOUND"
    http_status = 404
    default_message = "منبع مورد نظر یافت نشد."


class ConflictError(FxarsError):
    code = "CONFLICT"
    http_status = 409
    default_message = "وضعیت منبع با درخواست سازگار نیست."


class DataStaleError(FxarsError):
    code = "DATA_STALE"
    http_status = 409
    default_message = "داده بازار کهنه است؛ تصمیم‌گیری مجاز نیست."


class DataInvalidError(FxarsError):
    code = "DATA_INVALID"
    http_status = 422
    default_message = "داده بازار نامعتبر است."


class RiskRejectedError(FxarsError):
    code = "RISK_REJECTED"
    http_status = 422
    default_message = "دروازه ریسک درخواست را رد کرد."


class KillSwitchActiveError(FxarsError):
    code = "KILL_SWITCH_ACTIVE"
    http_status = 423
    default_message = "کلید توقف اضطراری فعال است."


class PhaseViolationError(FxarsError):
    code = "PHASE_VIOLATION"
    http_status = 403
    default_message = "این عملیات در فاز فعلی سامانه مجاز نیست."


class IdempotencyConflictError(FxarsError):
    code = "IDEMPOTENCY_CONFLICT"
    http_status = 409
    default_message = "کلید Idempotency با درخواست متفاوت قبلی تکراری است."


class BrokerUnavailableError(FxarsError):
    code = "BROKER_UNAVAILABLE"
    http_status = 503
    default_message = "اتصال به بروکر در دسترس نیست."


class ReproducibilityError(FxarsError):
    code = "REPRODUCIBILITY_ERROR"
    http_status = 500
    default_message = "بازتولید نتیجه با ورودی یکسان ممکن نشد."


class ScenarioTransitionError(FxarsError):
    code = "SCENARIO_TRANSITION_INVALID"
    http_status = 409
    default_message = "گذار وضعیت سناریو مجاز نیست."


class RateLimitedError(FxarsError):
    code = "RATE_LIMITED"
    http_status = 429
    default_message = "تعداد درخواست‌ها بیش از حد مجاز است."
