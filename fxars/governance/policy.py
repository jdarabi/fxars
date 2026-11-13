"""رجیستری سیاست — بخش ۳-۲ و ۱۲-۲ سند تکمیلی ۱.۱.

هر نسخه سیاست ریسک/تصمیم با هش محتوا ثبت می‌شود. تغییر سیاست فعال فقط با
factor مجاز و تأییدکننده مستقل انجام و در Audit ثبت می‌شود. سیاست فعال قبلی
`RETIRED` می‌شود تا همیشه یک سیاست فعال در هر نوع باقی بماند.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from fxars.audit.audit import AuditAction
from fxars.core.errors import ConflictError, NotFoundError, ValidationError
from fxars.core.hashing import sha256_obj
from fxars.core.timeutil import format_ts, parse_ts, utcnow
from fxars.storage.db import Database

KINDS = {"risk", "decision", "data", "execution"}
STATUSES = {"DRAFT", "ACTIVE", "RETIRED"}


class PolicyValidationError(ValidationError):
    pass


@dataclass(frozen=True)
class PolicyRecord:
    policy_id: str
    version: str
    kind: str
    status: str
    content_hash: str
    values: dict[str, Any]
    actor: str
    approved_by: str
    notes: str
    created_at: datetime
    activated_at: datetime | None = None
    supersedes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "kind": self.kind,
            "status": self.status,
            "content_hash": self.content_hash,
            "values": self.values,
            "actor": self.actor,
            "approved_by": self.approved_by,
            "notes": self.notes,
            "created_at": format_ts(self.created_at),
            "activated_at": format_ts(self.activated_at) if self.activated_at else None,
            "supersedes": self.supersedes,
        }


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


class PolicyRegistry:
    def __init__(self, db: Database, audit, clock: Callable[[], datetime] | None = None) -> None:
        self.db = db
        self.audit = audit
        self.clock = clock or utcnow

    def register(
        self,
        kind: str,
        values: dict[str, Any],
        *,
        actor: str,
        version: str | None = None,
        approved_by: str = "",
        notes: str = "",
        activate: bool = False,
    ) -> PolicyRecord:
        kind = str(kind).strip().lower()
        if kind not in KINDS:
            raise PolicyValidationError(f"نوع سیاست نامعتبر است: {kind}")
        if not isinstance(values, dict) or not values:
            raise PolicyValidationError("مقدار سیاست باید یک شیء غیرخالی باشد.")
        if not actor.strip():
            raise PolicyValidationError("ثبت سیاست نیازمند actor است.")
        content_hash = sha256_obj({"kind": kind, "values": values})
        resolved_version = version or f"{kind}-{content_hash[:12]}"
        existing = self.get(resolved_version, kind=kind)
        if existing is not None:
            if existing.content_hash != content_hash:
                raise ConflictError(
                    "نسخه سیاست با محتوای متفاوت قبلاً ثبت شده است.",
                    details={"policy_id": existing.policy_id, "version": resolved_version},
                )
            return existing
        when = self.clock()
        record = PolicyRecord(
            policy_id=f"{kind}:{content_hash[:16]}",
            version=resolved_version,
            kind=kind,
            status="DRAFT",
            content_hash=content_hash,
            values=dict(values),
            actor=actor,
            approved_by=approved_by,
            notes=notes,
            created_at=when,
        )
        self._save(record)
        self.audit.append(
            AuditAction.POLICY_RECORDED,
            "policy",
            record.policy_id,
            actor=actor,
            payload={
                "kind": kind,
                "version": resolved_version,
                "content_hash": content_hash,
                "status": "DRAFT",
                "note_len": len(notes),
            },
        )
        if activate:
            return self.activate(record.version, kind=kind, actor=actor, approved_by=approved_by,
                                 reason=notes or "initial activation")
        return record

    def activate(
        self, version: str, *, kind: str, actor: str, approved_by: str, reason: str
    ) -> PolicyRecord:
        record = self.get(version, kind=kind)
        if record is None:
            raise NotFoundError(f"نسخه سیاست یافت نشد: {version}")
        if record.status == "ACTIVE":
            return record
        if not approved_by.strip():
            raise PolicyValidationError("فعال‌سازی سیاست نیازمند تأییدکننده مستقل است.")
        if approved_by == actor:
            raise PolicyValidationError("تأییدکننده نباید همان ثبت‌کننده سیاست باشد.")
        if not reason.strip():
            raise PolicyValidationError("فعال‌سازی سیاست نیازمند دلیل است.")
        current = self.current(kind)
        when = self.clock()
        supersedes = current.version if current else None
        if current is not None and current.version != record.version:
            self._save(_replace_status(current, "RETIRED"))
        activated = replace(
            record,
            status="ACTIVE",
            activated_at=when,
            approved_by=approved_by,
            supersedes=supersedes,
        )
        self._save(activated)
        self.audit.append(
            AuditAction.POLICY_CHANGED,
            "policy",
            activated.policy_id,
            actor=actor,
            payload={
                "kind": kind,
                "version": version,
                "content_hash": activated.content_hash,
                "supersedes": supersedes,
                "approved_by": approved_by,
                "reason": reason,
            },
        )
        return activated

    def current(self, kind: str) -> PolicyRecord | None:
        row = self.db.query_one(
            "SELECT payload FROM policy_registry WHERE kind = ? AND status = 'ACTIVE' "
            "ORDER BY updated_at DESC, version DESC LIMIT 1",
            (kind,),
        )
        return self._decode(row) if row else None

    def get(self, version: str, *, kind: str) -> PolicyRecord | None:
        row = self.db.query_one(
            "SELECT payload FROM policy_registry WHERE kind = ? AND version = ?",
            (kind, version),
        )
        return self._decode(row) if row else None

    def list(self, *, kind: str | None = None, limit: int = 100) -> list[PolicyRecord]:
        if kind:
            rows = self.db.query(
                "SELECT payload FROM policy_registry WHERE kind = ? ORDER BY updated_at DESC LIMIT ?",
                (kind, limit),
            )
        else:
            rows = self.db.query(
                "SELECT payload FROM policy_registry ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
        return [self._decode(row) for row in rows]

    def ensure_active(self, kind: str, values: dict[str, Any], *, actor: str = "system") -> PolicyRecord:
        """اگر سیاست فعال با این محتوا وجود ندارد، نسخه سیاست فعلی را ثبت می‌کند."""
        content_hash = sha256_obj({"kind": kind, "values": values})
        current = self.current(kind)
        if current is not None and current.content_hash == content_hash:
            return current
        record = self.register(kind, values, actor=actor, notes="seed current configuration")
        return self.activate(
            record.version,
            kind=kind,
            actor=actor,
            approved_by="governance-seed",
            reason="ثبت سیاست جاری هنگام راه‌اندازی",
        )

    def _save(self, record: PolicyRecord) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO policy_registry "
            "(policy_id, version, kind, status, updated_at, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.policy_id,
                record.version,
                record.kind,
                record.status,
                format_ts(self.clock()),
                _dump(record.to_dict()),
            ),
        )

    @staticmethod
    def _decode(row: Any) -> PolicyRecord:
        data = json.loads(row["payload"])
        return PolicyRecord(
            policy_id=data["policy_id"],
            version=data["version"],
            kind=data["kind"],
            status=data["status"],
            content_hash=data["content_hash"],
            values=data.get("values", {}),
            actor=data.get("actor", ""),
            approved_by=data.get("approved_by", ""),
            notes=data.get("notes", ""),
            created_at=parse_ts(data["created_at"]),
            activated_at=parse_ts(data["activated_at"]) if data.get("activated_at") else None,
            supersedes=data.get("supersedes"),
        )


def _replace_status(record: PolicyRecord, status: str) -> PolicyRecord:
    return PolicyRecord(
        policy_id=record.policy_id,
        version=record.version,
        kind=record.kind,
        status=status,
        content_hash=record.content_hash,
        values=record.values,
        actor=record.actor,
        approved_by=record.approved_by,
        notes=record.notes,
        created_at=record.created_at,
        activated_at=record.activated_at,
        supersedes=record.supersedes,
    )
