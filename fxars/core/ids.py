"""شناسه‌های پایدار و قابل بازتولید.

شناسه‌های مشتق‌شده از محتوا (stable_id) باعث می‌شوند اجرای دوباره با ورودی یکسان
همان شناسه/هش را تولید کند؛ الزام Determinism و AC-02.
"""

from __future__ import annotations

import secrets
from typing import Any

from fxars.core.hashing import sha256_obj


def stable_id(prefix: str, *parts: Any, length: int = 20) -> str:
    digest = sha256_obj(list(parts))[:length]
    return f"{prefix}_{digest}"


def new_id(prefix: str, length: int = 16) -> str:
    return f"{prefix}_{secrets.token_hex(length // 2)}"


def correlation_id() -> str:
    return new_id("corr", 24)


def order_client_id(instrument_id: str, stamp: str, sequence: int) -> str:
    return f"fxars-{instrument_id.lower()}-{stamp}-{sequence:04d}"
