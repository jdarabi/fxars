"""لایهٔ مدیریت کلید (KMS) برای اسرار و امضای زنجیرهٔ ممیزی.

دو تأمین‌کننده دارد:
- ``local``: مشتق‌شده از ``security.secret_key`` برای توسعه/تک‌نمونه.
- ``env``: کلید اصلی ۳۲+ بایتی از ``FXARS_KMS_MASTER_KEY`` (hex/base64) که از
  Secret Manager/KMS تزریق می‌شود؛ کلید قبلی برای چرخش با
  ``FXARS_KMS_MASTER_KEY_PREVIOUS`` پذیرفته می‌شود.

کلید هر کاربرد با HMAC-SHA256 از کلید اصلی مشتق می‌شود تا سرریز یک کاربرد به
کاربرد دیگر رخ ندهد. هیچ‌جا مقدار کلید لاگ یا بازگردانده نمی‌شود.
"""

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

MIN_MASTER_KEY_BYTES = 32
MASTER_KEY_ENV = "FXARS_KMS_MASTER_KEY"
PREVIOUS_MASTER_KEY_ENV = "FXARS_KMS_MASTER_KEY_PREVIOUS"


class KmsError(RuntimeError):
    """خطای پیکربندی یا دسترسی به کلید."""


@dataclass(frozen=True)
class KeyMaterial:
    key_id: str
    key: bytes = field(repr=False)


class KeyProvider(Protocol):
    name: str

    def current(self, purpose: str) -> KeyMaterial: ...

    def by_id(self, purpose: str, key_id: str) -> KeyMaterial | None: ...


def _key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def _derive(master: bytes, purpose: str) -> bytes:
    import hmac

    return hmac.new(master, b"fxars-kms|" + purpose.encode("utf-8"), hashlib.sha256).digest()


def _material(master: bytes, purpose: str) -> KeyMaterial:
    key = _derive(master, purpose)
    return KeyMaterial(key_id=_key_id(key), key=key)


class LocalKeyProvider:
    """کلید محلی مشتق‌شده از ``security.secret_key`` (پیش‌فرض توسعه)."""

    name = "local"

    def __init__(self, secret_key: str) -> None:
        if not secret_key:
            raise KmsError("secret_key برای KMS محلی خالی است.")
        self._master = hashlib.sha256(("fxars-kms-local|" + secret_key).encode("utf-8")).digest()
        self._cache: dict[str, KeyMaterial] = {}

    def _get(self, purpose: str) -> KeyMaterial:
        material = self._cache.get(purpose)
        if material is None:
            material = _material(self._master, purpose)
            self._cache[purpose] = material
        return material

    def current(self, purpose: str) -> KeyMaterial:
        return self._get(purpose)

    def by_id(self, purpose: str, key_id: str) -> KeyMaterial | None:
        material = self._get(purpose)
        return material if material.key_id == key_id else None


class EnvKeyProvider:
    """کلید اصلی تزریق‌شده از محیط/Secret Manager با پشتیبانی از چرخش."""

    name = "env"

    def __init__(self, master: bytes, *, previous: bytes | None = None) -> None:
        _require_length(master, MASTER_KEY_ENV)
        if previous is not None:
            _require_length(previous, PREVIOUS_MASTER_KEY_ENV)
        self._master = master
        self._previous = previous
        self._cache: dict[tuple[str, str], KeyMaterial] = {}

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> EnvKeyProvider:
        env = environ if environ is not None else os.environ
        current = env.get(MASTER_KEY_ENV, "").strip()
        if not current:
            raise KmsError(f"{MASTER_KEY_ENV} تنظیم نشده است؛ برای kms_provider=env لازم است.")
        previous_text = env.get(PREVIOUS_MASTER_KEY_ENV, "").strip()
        previous = _parse_master(previous_text, PREVIOUS_MASTER_KEY_ENV) if previous_text else None
        return cls(_parse_master(current, MASTER_KEY_ENV), previous=previous)

    def _get(self, master: bytes, purpose: str) -> KeyMaterial:
        cache_key = (_key_id(master), purpose)
        material = self._cache.get(cache_key)
        if material is None:
            material = _material(master, purpose)
            self._cache[cache_key] = material
        return material

    def current(self, purpose: str) -> KeyMaterial:
        return self._get(self._master, purpose)

    def by_id(self, purpose: str, key_id: str) -> KeyMaterial | None:
        candidate = self._get(self._master, purpose)
        if candidate.key_id == key_id:
            return candidate
        if self._previous is not None:
            previous = self._get(self._previous, purpose)
            if previous.key_id == key_id:
                return previous
        return None


def _parse_master(value: str, name: str) -> bytes:
    text = value.strip()
    try:
        raw = bytes.fromhex(text)
    except ValueError:
        try:
            padded = text + "=" * (-len(text) % 4)
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        except Exception as exc:  # noqa: BLE001 - پیام یکنواخت برای پیکربندی نامعتبر
            raise KmsError(f"{name} باید hex یا base64 باشد.") from exc
    _require_length(raw, name)
    return raw


def _require_length(raw: bytes, name: str) -> None:
    if len(raw) < MIN_MASTER_KEY_BYTES:
        raise KmsError(
            f"{name} باید حداقل {MIN_MASTER_KEY_BYTES} بایت آنتروپی باشد (مقدار چاپ نمی‌شود)."
        )


def build_key_provider(settings, environ: Mapping[str, str] | None = None) -> KeyProvider:
    provider = settings.security.kms_provider
    if provider == "env":
        return EnvKeyProvider.from_environ(environ)
    if provider == "local":
        return LocalKeyProvider(settings.security.secret_key)
    raise KmsError(f"kms_provider ناشناخته: {provider!r}")
