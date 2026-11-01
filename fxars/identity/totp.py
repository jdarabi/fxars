"""TOTP (RFC 6238) بدون وابستگی خارجی."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _normalize(secret: str) -> bytes:
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(padded)


def hotp(secret: str, counter: int, digits: int = 6) -> str:
    key = _normalize(secret)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def totp(secret: str, *, at: float | None = None, period: int = 30, digits: int = 6) -> str:
    moment = time.time() if at is None else at
    return hotp(secret, int(moment // period), digits)


def verify_totp(secret: str, code: str, *, at: float | None = None, period: int = 30,
                digits: int = 6, window: int = 1) -> bool:
    if not code or not code.isdigit() or len(code) != digits:
        return False
    moment = time.time() if at is None else at
    counter = int(moment // period)
    for offset in range(-window, window + 1):
        if hmac.compare_digest(hotp(secret, counter + offset, digits), code):
            return True
    return False


def provisioning_uri(secret: str, username: str, issuer: str = "FX-ARS") -> str:
    label = quote(f"{issuer}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
