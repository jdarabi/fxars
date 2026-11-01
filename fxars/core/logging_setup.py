"""لاگ ساختاریافته JSON، بدون اسرار، همراه correlation_id."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from fxars.core.context import current_correlation_id
from fxars.core.serde import jsonable

_SECRET_KEYS = {"password", "token", "secret", "authorization", "api_key", "totp", "cookie"}


def _redact(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            key: ("***" if any(marker in str(key).lower() for marker in _SECRET_KEYS) else _redact(value))
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [_redact(item) for item in data]
    return data


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None) or current_correlation_id(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "data", None)
        if extra:
            payload["data"] = _redact(jsonable(extra))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, stream: Any = None) -> None:
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("fxars")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False


def get_logger(name: str = "fxars") -> logging.Logger:
    return logging.getLogger(name if name.startswith("fxars") else f"fxars.{name}")
