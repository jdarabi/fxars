"""اتصال سراسری MetaTrader5 با شمارش مرجع.

`mt5.initialize()` و `mt5.shutdown()` در سطح فرایند عمل می‌کنند؛ اگر هر درخواست
API اتصال خود را باز و بلافاصله ببندد، اتصال بروکر/فید مشترک نیز قطع می‌شود.
تمام مصرف‌کننده‌ها (فید، بروکر، تاریخچه) باید از این مدیر استفاده کنند تا
`shutdown` فقط هنگام آزادشدن آخرین مرجع اجرا شود.
"""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.RLock()
_module: Any = None
_refs = 0


class MT5ConnectionError(RuntimeError):
    """اتصال به ترمینال MT5 برقرار نشد."""


def acquire(mt5: Any | None = None) -> Any:
    """یک مرجع اتصال می‌گیرد و ماژول MT5 مقداردهی‌شده را برمی‌گرداند."""
    global _module, _refs
    with _lock:
        if mt5 is None:
            try:
                import MetaTrader5 as mt5_module
            except ImportError as exc:  # pragma: no cover - وابسته به محیط
                raise MT5ConnectionError("MetaTrader5 package نصب نیست") from exc
            mt5 = mt5_module
        if _module is not None and _module is not mt5:
            # ماژول متفاوت (مثلاً fake در تست‌ها): کش قبلی معتبر نیست.
            _module = None
            _refs = 0
        if _module is None:
            if not mt5.initialize():
                code, msg = mt5.last_error()
                raise MT5ConnectionError(f"MT5 initialize failed: ({code}) {msg}")
            _module = mt5
            _refs = 1
        else:
            _refs += 1
        return _module


def release() -> None:
    """یک مرجع را آزاد می‌کند؛ آخرین مرجع اتصال را می‌بندد."""
    global _module, _refs
    with _lock:
        if _module is None:
            return
        _refs = max(0, _refs - 1)
        if _refs == 0:
            module, _module = _module, None
            try:
                module.shutdown()
            except Exception:
                pass


def reference_count() -> int:
    with _lock:
        return _refs


def reset_for_tests() -> None:
    global _module, _refs
    with _lock:
        _module = None
        _refs = 0
