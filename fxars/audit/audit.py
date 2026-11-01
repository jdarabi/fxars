"""ممیزی فقط‌افزودنی با زنجیره هش (Audit hash-chain).

هر رکورد هش رکورد قبلی را در بر می‌گیرد؛ حذف/ویرایش با Trigger پایگاه داده ممنوع است
و دستکاری زنجیره در verify() آشکار می‌شود (AC-10).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from fxars.core.context import current_actor, current_correlation_id
from fxars.core.hashing import canonical_json, sha256_hex
from fxars.core.ids import stable_id
from fxars.core.timeutil import utcnow
from fxars.domain.models import AuditEntry
from fxars.storage.db import Database
from fxars.storage.repositories import AuditRepository


class AuditAction:
    DATA_INGESTED = "DATA_INGESTED"
    DATA_QUARANTINED = "DATA_QUARANTINED"
    ANALYSIS_COMPLETED = "ANALYSIS_COMPLETED"
    ANALYSIS_NO_TRADE = "ANALYSIS_NO_TRADE"
    SCENARIO_CREATED = "SCENARIO_CREATED"
    SCENARIO_TRANSITION = "SCENARIO_TRANSITION"
    RISK_EVALUATED = "RISK_EVALUATED"
    KILL_SWITCH_CHANGED = "KILL_SWITCH_CHANGED"
    USER_CREATED = "USER_CREATED"
    USER_LOGIN = "USER_LOGIN"
    USER_LOGIN_FAILED = "USER_LOGIN_FAILED"
    USER_LOGOUT = "USER_LOGOUT"
    DEMO_TOTP_ISSUED = "DEMO_TOTP_ISSUED"
    BACKTEST_COMPLETED = "BACKTEST_COMPLETED"
    LOCKED_TEST_OPENED = "LOCKED_TEST_OPENED"
    ORDER_INTENT_BLOCKED = "ORDER_INTENT_BLOCKED"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    OUTBOX_PUBLISHED = "OUTBOX_PUBLISHED"
    ACCESS_DENIED = "ACCESS_DENIED"


_GENESIS = "0" * 64


class AuditLog:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.repo = AuditRepository(db)

    def append(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        *,
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditEntry:
        when = occurred_at or utcnow()
        actor_name = actor or current_actor()
        corr = correlation_id or current_correlation_id()
        body = {
            "occurred_at": when,
            "actor": actor_name,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "correlation_id": corr,
            "payload": payload or {},
        }
        with self.db.transaction():
            last = self.repo.last()
            prev_hash = last.entry_hash if last else _GENESIS
            entry_hash = sha256_hex(prev_hash + "|" + canonical_json(body))
            event_id = stable_id("aud", prev_hash, body, length=24)
            entry = AuditEntry(
                seq=0,
                event_id=event_id,
                occurred_at=when,
                actor=actor_name,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                correlation_id=corr,
                payload=payload or {},
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
            self.repo.append(entry)
            seq = self.db.scalar("SELECT last_insert_rowid()")
            return replace(entry, seq=int(seq))

    def verify(self) -> dict[str, Any]:
        """بازسازی زنجیره و گزارش اولین شکست."""
        entries = self.repo.all()
        prev = _GENESIS
        for entry in entries:
            body = {
                "occurred_at": entry.occurred_at,
                "actor": entry.actor,
                "action": entry.action,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "correlation_id": entry.correlation_id,
                "payload": entry.payload,
            }
            expected = sha256_hex(prev + "|" + canonical_json(body))
            if entry.prev_hash != prev:
                return {"valid": False, "count": len(entries), "broken_seq": entry.seq, "reason": "prev_hash_mismatch"}
            if entry.entry_hash != expected:
                return {"valid": False, "count": len(entries), "broken_seq": entry.seq, "reason": "entry_hash_mismatch"}
            prev = entry.entry_hash
        return {"valid": True, "count": len(entries), "head": prev, "broken_seq": None, "reason": None}

    def list_entries(self, *, limit: int = 100, offset: int = 0, action: str | None = None,
                     entity_type: str | None = None) -> list[AuditEntry]:
        return self.repo.list(limit=limit, offset=offset, action=action, entity_type=entity_type)
