from pathlib import Path

path = Path("C:/FX/fxars/audit/handlers.py")
if path.exists():
    print("[SKIP] handlers.py already exists")
else:
    content = """FIX-08-OUTBOX-CONSUMER: consumerهای پیش‌فرض برای رویدادهای Outbox.

فلسفه:
* هر handler باید idempotent و کم‌خطر باشد.
* هیچ Side-effect دامنه‌ای (مثل ساخت سفارش) در این handlers نیست.
* فقط log و metric — اگر پردازش پیچیده لازم شد، در MVP-2 اضافه می‌شود.

اگر handler خطا بدهد:
* Outbox با attempts++ دوباره تلاش می‌کند.
* پس از max_attempts (پیش‌فرض 5) → dead-letter.
* از CLI یا API می‌توان dead-letterها را بررسی/پاک کرد.
\"\"\"
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fxars.core.logging_setup import get_logger
from fxars.domain.models import User

logger = get_logger(\"outbox.consumer\")


class ConsumerStats:
    \"\"\"شمارنده ساده برای هر نوع رویداد مصرف‌شده.\"\"\"

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def bump(self, event_type: str) -> None:
        self._counts[event_type] = self._counts.get(event_type, 0) + 1

    def snapshot(self) -> dict[str, int]:
        return dict(self._counts)


def _log_consumer(event_type: str, level: str = \"info\") -> Callable[[dict[str, Any]], None]:
    \"\"\"یک handler بساز که فقط log می‌کند.\"\"\"
    log_fn = getattr(logger, level)

    def handler(event: dict[str, Any]) -> None:
        log_fn(
            \"outbox event consumed\",
            extra={
                \"data\": {
                    \"event_type\": event_type,
                    \"event_id\": event.get(\"event_id\"),
                    \"correlation_id\": event.get(\"correlation_id\"),
                }
            },
        )

    return handler


def default_handlers(*, stats: ConsumerStats | None = None) -> dict[str, Callable[[dict[str, Any]], None]]:
    \"\"\"handlers پیش‌فرض برای همه event_typeهای شناخته‌شده.

    همه log می‌کنند و در stats جمع می‌شوند. اگر stats None باشد، فقط log.
    \"\"\"
    stats = stats or ConsumerStats()

    def make(event_type: str, level: str = \"info\") -> Callable[[dict[str, Any]], None]:
        base = _log_consumer(event_type, level)

        def handler(event: dict[str, Any]) -> None:
            stats.bump(event_type)
            base(event)

        return handler

    return {
        \"analysis.run.completed\": make(\"analysis.run.completed\"),
        \"risk.decision.created\": make(\"risk.decision.created\"),
        \"scenario.created\": make(\"scenario.created\"),
        \"scenario.transitioned\": make(\"scenario.transitioned\"),
        \"market_data.candles.ingested\": make(\"market_data.candles.ingested\"),
        \"market_data.quality.completed\": make(\"market_data.quality.completed\"),
        \"research.backtest.completed\": make(\"research.backtest.completed\"),
        \"system.kill_switch.changed\": make(\"system.kill_switch.changed\", \"warning\"),
        \"execution.order_intent.created\": make(\"execution.order_intent.created\"),
    }
"""
    path.write_text(content, encoding="utf-8")
    print("[WROTE] fxars/audit/handlers.py")