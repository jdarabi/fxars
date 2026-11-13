"""لنگر خارجی زنجیرهٔ ممیزی با امضای HMAC-SHA256 از کلید KMS.

خروجی این ماژول یک فایل JSON کوچک است که ``head`` و ``count`` زنجیره را امضا
می‌کند. نگهداری آن بیرون از پایگاه داده، بازنویسی/کوتاه‌سازی کل زنجیره با
بازسازی هش‌ها را آشکار می‌کند. کلید امضا از کاربرد ``audit-anchor`` در KMS
مشتق می‌شود و با چرخش کلید، لنگرهای قبلی همچنان قابل تأیید می‌مانند.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from fxars.core.hashing import canonical_json, hmac_sha256
from fxars.core.timeutil import format_ts, parse_ts, utcnow
from fxars.security.kms import KeyProvider, KmsError

ANCHOR_PURPOSE = "audit-anchor"
ANCHOR_VERSION = 1
ANCHOR_ALGORITHM = "HMAC-SHA256"


@dataclass(frozen=True)
class AuditAnchor:
    version: int
    key_id: str
    head: str
    count: int
    signed_at: datetime
    algorithm: str
    signature: str

    def signing_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "key_id": self.key_id,
            "head": self.head,
            "count": self.count,
            "signed_at": format_ts(self.signed_at),
            "algorithm": self.algorithm,
        }

    def to_dict(self) -> dict[str, Any]:
        data = self.signing_payload()
        data["signature"] = self.signature
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditAnchor:
        try:
            return cls(
                version=int(data["version"]),
                key_id=str(data["key_id"]),
                head=str(data["head"]),
                count=int(data["count"]),
                signed_at=parse_ts(str(data["signed_at"])),
                algorithm=str(data["algorithm"]),
                signature=str(data["signature"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"لنگر ممیزی نامعتبر است: {exc}") from exc


class AuditAnchorSigner:
    def __init__(self, provider: KeyProvider, *, purpose: str = ANCHOR_PURPOSE) -> None:
        self.provider = provider
        self.purpose = purpose

    def sign(self, verification: dict[str, Any], *, signed_at: datetime | None = None) -> AuditAnchor:
        if not verification.get("valid"):
            raise KmsError("زنجیرهٔ ممیزی معتبر نیست؛ امضا انجام نشد.")
        material = self.provider.current(self.purpose)
        anchor = AuditAnchor(
            version=ANCHOR_VERSION,
            key_id=material.key_id,
            head=str(verification["head"]),
            count=int(verification["count"]),
            signed_at=signed_at or utcnow(),
            algorithm=ANCHOR_ALGORITHM,
            signature="",
        )
        signature = hmac_sha256(
            material.key, canonical_json(anchor.signing_payload()).encode("utf-8")
        ).hex()
        return replace(anchor, signature=signature)

    def verify(self, anchor: AuditAnchor, verification: dict[str, Any]) -> dict[str, Any]:
        if anchor.version != ANCHOR_VERSION or anchor.algorithm != ANCHOR_ALGORITHM:
            return self._result(anchor, False, "unsupported_anchor_version", False, False)
        material = self.provider.by_id(self.purpose, anchor.key_id)
        if material is None:
            return self._result(anchor, False, "unknown_key", False, False)
        expected = hmac_sha256(
            material.key, canonical_json(anchor.signing_payload()).encode("utf-8")
        ).hex()
        signature_valid = hmac.compare_digest(anchor.signature, expected)
        chain_matches = bool(verification.get("valid")) and (
            anchor.head == verification.get("head") and anchor.count == int(verification.get("count", -1))
        )
        if not signature_valid:
            return self._result(anchor, False, "signature_invalid", False, chain_matches)
        if not chain_matches:
            return self._result(anchor, False, "chain_mismatch", True, False)
        return self._result(anchor, True, None, True, True)

    @staticmethod
    def _result(anchor: AuditAnchor, valid: bool, reason: str | None,
                signature_valid: bool, chain_matches: bool) -> dict[str, Any]:
        return {
            "valid": valid,
            "reason": reason,
            "signature_valid": signature_valid,
            "chain_matches": chain_matches,
            "key_id": anchor.key_id,
            "head": anchor.head,
            "count": anchor.count,
            "signed_at": format_ts(anchor.signed_at),
        }
