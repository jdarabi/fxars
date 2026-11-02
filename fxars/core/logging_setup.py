"""لاگ ساختاریافته JSON، بدون اسرار، همراه correlation_id و trace_id."""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fxars.core.context import current_correlation_id
from fxars.core.serde import jsonable
from fxars.core.timeutil import utcnow

_SECRET_KEYS = {
    "password", "passwd", "token", "secret", "authorization",
    "api_key", "apikey", "totp", "totp_code", "cookie", "set-cookie",
    "private_key", "session_token", "idempotency-key", "refresh_token",
    "access_token", "bearer", "auth",
}

# Patterns for redacting secret values inside strings
_SECRET_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization: Bearer <token>
    (re.compile(r"(?i)(bearer\s+)([A-Za-z0-9\-_.~+/]+=*)"), r"\1***"),
    # Authorization: Basic <base64>
    (re.compile(r"(?i)(basic\s+)([A-Za-z0-9+/=]+)"), r"\1***"),
    # Long hex or base64 tokens (>= 32 chars) - likely secrets
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "***"),
    # JWT-like tokens: header.payload.signature
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "***"),
    # API keys with prefixes
    (re.compile(r"\b(sk|pk|rk)_(live|test)_[A-Za-z0-9]{16,}\b"), "***"),
)


def _redact_string(value: str) -> str:
    """Redact known secret patterns inside a string."""
    if not isinstance(value, str):
        return value
    result = value
    for pattern, replacement in _SECRET_VALUE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _redact(data: Any) -> Any:
    """Recursively redact secret keys and values."""
    if isinstance(data, dict):
        return {
            key: (
                "***"
                if any(marker in str(key).lower() for marker in _SECRET_KEYS)
                else _redact(value)
            )
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple, set, frozenset)):
        return [_redact(item) for item in data]
    if isinstance(data, str):
        return _redact_string(data)
    return data


class JsonFormatter(logging.Formatter):
    """JSON formatter with correlation_id, trace_id, and redaction."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": _redact_string(record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", None) or current_correlation_id(),
        }
        # trace_id for future distributed tracing (not required for MVP-1)
        trace_id = getattr(record, "trace_id", None)
        if trace_id:
            payload["trace_id"] = trace_id

        if record.exc_info:
            payload["exception"] = _redact_string(self.formatException(record.exc_info))

        # Custom fields via extra={"data": {...}}
        extra = getattr(record, "data", None)
        if extra:
            payload["data"] = _redact(jsonable(extra))

        # Path info (file:line)
        if record.pathname:
            payload["source"] = f"{Path(record.pathname).name}:{record.lineno}"

        return json.dumps(payload, ensure_ascii=False)


class ErrorFileHandler(logging.Handler):
    """Append ERROR+ logs to a JSONL file with simple rotation.

    Keeps the last N lines by rewriting on rotation (simple, no extra deps).
    """

    def __init__(self, path: Path, max_lines: int = 10_000) -> None:
        super().__init__(level=logging.ERROR)
        self.path = Path(path)
        self.max_lines = max_lines
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.formatter = JsonFormatter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            with self._lock:
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(message + "\n")
                self._maybe_rotate()
        except Exception:
            self.handleError(record)

    def _maybe_rotate(self) -> None:
        if self.max_lines <= 0:
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
            if len(lines) > self.max_lines:
                with open(self.path, "w", encoding="utf-8") as handle:
                    handle.writelines(lines[-self.max_lines:])
        except FileNotFoundError:
            pass


def configure_logging(
    level: str = "INFO",
    *,
    stream: Any = None,
    error_log_path: str | Path | None = None,
) -> None:
    """Configure the root fxars logger.

    Args:
        level: minimum level (INFO, DEBUG, WARNING, ERROR).
        stream: stream to write to (default: sys.stderr).
        error_log_path: if set, ERROR+ records are also written to this JSONL file.
    """
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("fxars")
    root.handlers.clear()
    root.addHandler(handler)
    if error_log_path is not None:
        error_handler = ErrorFileHandler(Path(error_log_path))
        root.addHandler(error_handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False


def get_logger(name: str = "fxars") -> logging.Logger:
    return logging.getLogger(name if name.startswith("fxars") else f"fxars.{name}")