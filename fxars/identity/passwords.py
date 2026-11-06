"""رمزنگاری رمز عبور (PBKDF2-HMAC-SHA256) و جعبه اسرار سبک."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from fxars.core.hashing import hmac_sha256


def hash_password(password: str, *, iterations: int = 210_000) -> str:
    if len(password) < 10:
        raise ValueError("رمز عبور باید حداقل ۱۰ کاراکتر باشد.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
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

    در استقرار واقعی باید با KMS/Secret Manager جایگزین شود؛ این پیاده‌سازی برای
    جلوگیری از ذخیره متن‌رو در پایگاه داده مرجع است.
    """

    def __init__(self, key_material: str) -> None:
        self._key = hashlib.sha256(("fxars-secretbox|" + key_material).encode("utf-8")).digest()

    def _keystream(self, nonce: bytes, length: int) -> bytes:
        blocks = []
        counter = 0
        while sum(len(block) for block in blocks) < length:
            blocks.append(hmac_sha256(self._key, nonce + counter.to_bytes(4, "big")))
            counter += 1
        return b"".join(blocks)[:length]

    def encrypt(self, plaintext: str) -> str:
        nonce = secrets.token_bytes(16)
        data = plaintext.encode("utf-8")
        stream = self._keystream(nonce, len(data))
        ciphertext = bytes(a ^ b for a, b in zip(data, stream, strict=True))
        tag = hmac_sha256(self._key, nonce + ciphertext)[:16]
        return base64.urlsafe_b64encode(nonce + ciphertext + tag).decode("ascii")

    def decrypt(self, encoded: str) -> str:
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
        nonce, ciphertext, tag = raw[:16], raw[16:-16], raw[-16:]
        expected = hmac_sha256(self._key, nonce + ciphertext)[:16]
        if not hmac.compare_digest(tag, expected):
            raise ValueError("tag جعبه اسرار معتبر نیست.")
        stream = self._keystream(nonce, len(ciphertext))
        return bytes(a ^ b for a, b in zip(ciphertext, stream, strict=True)).decode("utf-8")
