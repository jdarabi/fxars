"""Transactional Outbox: انتشار رویداد پس از COMMIT همان تراکنش دامنه.

مصرف‌کننده باید idempotent باشد؛ outbox_consumed این تضمین را می‌دهد.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fxars.core.context import current_correlation_id
from fxars.core.errors import FxarsError
from fxars.core.ids import new_id
from fxars.core.logging_setup import get_logger
from fxars.core.timeutil import utcnow
from fxars.storage.db import Database
from fxars.storage.repositories import OutboxRepository

logger = get_logger("outbox")


class EventType:
    CANDLES_INGESTED = "market_data.candles.ingested"
    DATA_QUALITY_COMPLETED = "market_data.quality.completed"
    ANALYSIS_COMPLETED = "analysis.run.completed"
    SCENARIO_CREATED = "scenario.created"
    SCENARIO_TRANSITIONED = "scenario.transitioned"
    RISK_EVALUATED = "risk.decision.created"
    BACKTEST_COMPLETED = "research.backtest.completed"
    KILL_SWITCH_CHANGED = "system.kill_switch.changed"
    ORDER_INTENT_CREATED = "execution.order_intent.created"


class Outbox:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.repo = OutboxRepository(db)

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        schema_version: str = "1.0.0",
        occurred_at: datetime | None = None,
        event_id: str | None = None,
    ) -> str:
        identifier = event_id or new_id("evt", 20)
        self.repo.add(
            identifier,
            event_type,
            schema_version,
            occurred_at or utcnow(),
            current_correlation_id(),
            payload,
        )
        return identifier

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.repo.pending(limit)

    def publish_pending(
        self,
        handlers: dict[str, Callable[[dict[str, Any]], None]],
        *,
        limit: int = 100,
        max_attempts: int = 5,
    ) -> dict[str, int]:
        """FIX-09-OUTBOX-RETRY: پردازش با retry و dead-letter.

        * handler ناموجود ⇒ skip (نه publish) تا بعداً قابل پردازش باشد.
        * خطای handler ⇒ attempts++ و پس از max_attempts → dead-letter.
        """
        stats = {"published": 0, "failed": 0, "skipped": 0, "dead_lettered": 0}
        for event in self.pending(limit):
            handler = handlers.get(event["event_type"])
            if handler is None:
                stats["skipped"] += 1
                continue
            attempts = self.repo.attempts_for(event["event_id"])
            if attempts >= max_attempts:
                self.repo.mark_dead_letter(
                    event["event_id"], utcnow(), reason=f"max_attempts={max_attempts}",
                )
                stats["dead_lettered"] += 1
                continue
            try:
                handler(event)
            except FxarsError as exc:
                logger.warning(
                    "outbox handler failed",
                    extra={"data": {"event": event["event_id"], "error": exc.code, "attempt": attempts + 1}},
                )
                self.repo.bump_attempt(event["event_id"], last_error=str(exc))
                stats["failed"] += 1
                continue
            except Exception as exc:
                logger.exception(
                    "outbox handler crashed",
                    extra={"data": {"event": event["event_id"]}},
                )
                self.repo.bump_attempt(event["event_id"], last_error=type(exc).__name__)
                stats["failed"] += 1
                continue
            self.repo.mark_published(event["event_id"], utcnow())
            stats["published"] += 1
        return stats

    def consume_once(self, consumer: str, event_id: str, action: Callable[[], None]) -> bool:
        """اجرای idempotent؛ اگر قبلاً مصرف شده باشد False برمی‌گرداند."""
        if self.repo.is_consumed(consumer, event_id):
            return False
        action()
        self.repo.mark_consumed(consumer, event_id, utcnow())
        return True

    @property
    def pending_count(self) -> int:
        return self.repo.count_pending()
