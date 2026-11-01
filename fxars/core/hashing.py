"""هش‌های پایدار: SHA-256 روی JSON متعارف."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fxars.core.serde import jsonable


def canonical_json(obj: Any) -> str:
    return json.dumps(
        jsonable(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_obj(obj: Any) -> str:
    return sha256_hex(canonical_json(obj))


def sha256_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def short_hash(obj: Any, length: int = 12) -> str:
    return sha256_obj(obj)[:length]


def hmac_sha256(key: bytes, message: bytes) -> bytes:
    import hmac

    return hmac.new(key, message, hashlib.sha256).digest()
