"""رمزنگاری رمز عبور (PBKDF2-HMAC-SHA256) و جعبه اسرار سبک."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING

from fxars.core.hashing import hmac_sha256

if TYPE_CHECKING:
    from fxars.security.kms import KeyProvider

MAX_PASSWORD_LENGTH = 256  # FIX-08-MAX-PASSWORD: ضد CPU DoS

_V2_PREFIX = "v2:"


def hash_password(password: str, *, iterations: int = 210_000) -> str:
    if len(password) < 10:
        raise ValueError("رمز عبور باید حداقل ۱۰ کاراکتر باشد.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"رمز عبور نمی‌تواند بیش از {MAX_PASSWORD_LENGTH} کاراکتر باشد.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    # FIX-08-MAX-PASSWORD: جلوگیری از PBKDF2 روی ورودی عظیم
    if not isinstance(password, str) or len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(digest.hex(), digest_hex)


class SecretBox:
    """رمزنگاری متقارن سبک (HMAC-SHA256 CTR + tag) برای اسرار کوتاه مانند TOTP.

    بدون ``provider`` رفتار قدیمی (کلید مشتق‌شده از یک رشته) حفظ می‌شود. با
    ``provider`` خروجی نسخه‌دار ``v2:<key_id>:<payload>`` است و کلید از KMS
    می‌آید؛ متن‌های قدیمی با کلید legacy قابل خواندن می‌مانند و چرخش کلید با
    ``previous`` در تأمین‌کننده پشتیبانی می‌شود.
    """

    def __init__(
        self,
        key_material: str | None = None,
        *,
        provider: KeyProvider | None = None,
        purpose: str = "totp",
        legacy_key_material: str | None = None,
    ) -> None:
        if key_material is None and provider is None:
            raise ValueError("SecretBox به کلید یا KeyProvider نیاز دارد.")
        self._provider = provider
        self._purpose = purpose
        legacy_source = key_material if key_material is not None else (legacy_key_material or "")
        self._legacy_key = hashlib.sha256(
            ("fxars-secretbox|" + legacy_source).encode("utf-8")
        ).digest()

    @classmethod
    def from_provider(
        cls,
        provider: KeyProvider,
        *,
        purpose: str = "totp",
        legacy_key_material: str | None = None,
    ) -> SecretBox:
        return cls(provider=provider, purpose=purpose, legacy_key_material=legacy_key_material)

    @property
    def key_id(self) -> str | None:
        return self._provider.current(self._purpose).key_id if self._provider is not None else None

    def _keystream(self, key: bytes, nonce: bytes, length: int) -> bytes:
        blocks = []
        counter = 0
        while sum(len(block) for block in blocks) < length:
            blocks.append(hmac_sha256(key, nonce + counter.to_bytes(4, "big")))
            counter += 1
        return b"".join(blocks)[:length]

    def encrypt(self, plaintext: str) -> str:
        nonce = secrets.token_bytes(16)
        data = plaintext.encode("utf-8")
        if self._provider is None:
            key, prefix = self._legacy_key, ""
        else:
            material = self._provider.current(self._purpose)
            key, prefix = material.key, f"{_V2_PREFIX}{material.key_id}:"
        stream = self._keystream(key, nonce, len(data))
        ciphertext = bytes(a ^ b for a, b in zip(data, stream, strict=True))
        tag = hmac_sha256(key, nonce + ciphertext)[:16]
        return prefix + base64.urlsafe_b64encode(nonce + ciphertext + tag).decode("ascii")

    def decrypt(self, encoded: str) -> str:
        if encoded.startswith(_V2_PREFIX):
            if self._provider is None:
                raise ValueError("متن رمز نسخهٔ KMS است اما هیچ KeyProvider پیکربندی نشده است.")
            key_id, _, payload = encoded[len(_V2_PREFIX):].partition(":")
            material = self._provider.by_id(self._purpose, key_id)
            if material is None:
                raise ValueError(f"کلید {key_id} برای این کاربرد در KMS موجود نیست.")
            key = material.key
        else:
            key, payload = self._legacy_key, encoded
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        nonce, ciphertext, tag = raw[:16], raw[16:-16], raw[-16:]
        expected = hmac_sha256(key, nonce + ciphertext)[:16]
        if not hmac.compare_digest(tag, expected):
            raise ValueError("tag جعبه اسرار معتبر نیست.")
        stream = self._keystream(key, nonce, len(ciphertext))
        return bytes(a ^ b for a, b in zip(ciphertext, stream, strict=True)).decode("utf-8")
