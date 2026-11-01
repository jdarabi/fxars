"""تبدیل ساختارهای دامنه به JSON پایدار (قرارداد API و هش)."""

from __future__ import annotations

import dataclasses
import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fxars.core.timeutil import format_ts


def jsonable(obj: Any) -> Any:
    """تبدیل بازگشتی به انواع قابل سریال‌سازی JSON."""
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):  # NaN/Inf
            return None
        return obj
    if isinstance(obj, Decimal):
        return format(obj, "f")
    if isinstance(obj, datetime):
        return format_ts(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, enum.Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {field.name: jsonable(getattr(obj, field.name)) for field in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(key): jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [jsonable(item) for item in obj]
    if hasattr(obj, "to_dict"):
        return jsonable(obj.to_dict())
    return str(obj)


def omit_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
