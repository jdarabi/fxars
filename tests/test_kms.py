"""آزمون لایهٔ KMS، جعبهٔ اسرار نسخه‌دار و لنگر امضای ممیزی."""

from __future__ import annotations

import base64
import unittest
from dataclasses import replace

from fxars.audit.anchor import AuditAnchor, AuditAnchorSigner
from fxars.config.settings import Settings
from fxars.identity.passwords import SecretBox
from fxars.security.kms import (
    EnvKeyProvider,
    KmsError,
    LocalKeyProvider,
    build_key_provider,
)


class LocalProviderTests(unittest.TestCase):
    def test_purpose_keys_are_deterministic_and_separated(self) -> None:
        first = LocalKeyProvider("unit-test-secret")
        second = LocalKeyProvider("unit-test-secret")
        self.assertEqual(first.current("totp"), second.current("totp"))
        self.assertNotEqual(first.current("totp").key, first.current("audit-anchor").key)
        self.assertEqual(len(first.current("totp").key), 32)
        material = first.current("totp")
        self.assertEqual(first.by_id("totp", material.key_id), material)
        self.assertIsNone(first.by_id("totp", "deadbeef"))

    def test_empty_secret_rejected(self) -> None:
        with self.assertRaises(KmsError):
            LocalKeyProvider("")

    def test_build_selects_provider(self) -> None:
        settings = Settings.from_dict({"security": {"kms_provider": "local", "secret_key": "x" * 40}})
        self.assertIsInstance(build_key_provider(settings), LocalKeyProvider)
        env_settings = replace(
            settings,
            security=replace(settings.security, kms_provider="env"),
        )
        with self.assertRaises(KmsError):
            build_key_provider(env_settings, environ={})


class EnvProviderTests(unittest.TestCase):
    def test_missing_or_short_key_rejected(self) -> None:
        with self.assertRaises(KmsError):
            EnvKeyProvider.from_environ({})
        with self.assertRaises(KmsError):
            EnvKeyProvider.from_environ({"FXARS_KMS_MASTER_KEY": "abcd"})
        with self.assertRaises(KmsError):
            EnvKeyProvider(bytes(16))

    def test_hex_and_base64_master_accepted(self) -> None:
        from_hex = EnvKeyProvider.from_environ({"FXARS_KMS_MASTER_KEY": "ab" * 32})
        encoded = base64.urlsafe_b64encode(b"cd" * 16).decode("ascii")
        from_b64 = EnvKeyProvider.from_environ({"FXARS_KMS_MASTER_KEY": encoded})
        self.assertNotEqual(from_hex.current("totp").key, from_b64.current("totp").key)

    def test_rotation_decrypts_previous_key(self) -> None:
        old = EnvKeyProvider(b"A" * 32)
        old_box = SecretBox.from_provider(old, legacy_key_material="legacy-secret")
        token = old_box.encrypt("totp-secret")
        self.assertTrue(token.startswith("v2:"))

        rotated = EnvKeyProvider(b"B" * 32, previous=b"A" * 32)
        new_box = SecretBox.from_provider(rotated, legacy_key_material="legacy-secret")
        self.assertEqual(new_box.decrypt(token), "totp-secret")
        self.assertIsNotNone(rotated.by_id("totp", old.current("totp").key_id))
        self.assertEqual(rotated.current("totp").key_id, new_box.key_id)

        without_previous = EnvKeyProvider(b"B" * 32)
        with self.assertRaises(ValueError):
            SecretBox.from_provider(without_previous).decrypt(token)


class SecretBoxProviderTests(unittest.TestCase):
    def test_legacy_roundtrip_unchanged(self) -> None:
        box = SecretBox("key")
        token = box.encrypt("secret-value")
        self.assertFalse(token.startswith("v2:"))
        self.assertEqual(box.decrypt(token), "secret-value")

    def test_provider_box_reads_legacy_ciphertext(self) -> None:
        legacy = SecretBox("shared-secret").encrypt("old-secret")
        box = SecretBox.from_provider(
            LocalKeyProvider("shared-secret"), legacy_key_material="shared-secret"
        )
        self.assertEqual(box.decrypt(legacy), "old-secret")

    def test_tampered_payload_rejected(self) -> None:
        box = SecretBox.from_provider(LocalKeyProvider("k"))
        token = box.encrypt("value")
        prefix, key_id, payload = token.split(":", 2)
        raw = bytearray(base64.urlsafe_b64decode(payload.encode("ascii")))
        raw[20] ^= 1
        tampered = f"{prefix}:{key_id}:" + base64.urlsafe_b64encode(bytes(raw)).decode("ascii")
        with self.assertRaises(ValueError):
            box.decrypt(tampered)

    def test_kms_ciphertext_requires_provider(self) -> None:
        token = SecretBox.from_provider(LocalKeyProvider("k")).encrypt("value")
        with self.assertRaises(ValueError):
            SecretBox("k").decrypt(token)


class AuditAnchorTests(unittest.TestCase):
    VERIFICATION = {"valid": True, "head": "a" * 64, "count": 7, "broken_seq": None, "reason": None}

    def test_sign_and_verify_roundtrip(self) -> None:
        signer = AuditAnchorSigner(LocalKeyProvider("anchor-secret"))
        anchor = signer.sign(self.VERIFICATION)
        self.assertEqual(len(anchor.signature), 64)
        result = signer.verify(anchor, self.VERIFICATION)
        self.assertTrue(result["valid"])
        self.assertTrue(result["signature_valid"])
        self.assertTrue(result["chain_matches"])
        self.assertIsNone(result["reason"])

        restored = AuditAnchor.from_dict(anchor.to_dict())
        self.assertEqual(restored, anchor)

    def test_changed_head_fails_chain_check(self) -> None:
        signer = AuditAnchorSigner(LocalKeyProvider("anchor-secret"))
        anchor = signer.sign(self.VERIFICATION)
        changed = dict(self.VERIFICATION, head="b" * 64)
        result = signer.verify(anchor, changed)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "chain_mismatch")
        self.assertTrue(result["signature_valid"])

    def test_tampered_signature_rejected(self) -> None:
        signer = AuditAnchorSigner(LocalKeyProvider("anchor-secret"))
        anchor = signer.sign(self.VERIFICATION)
        tampered = replace(anchor, signature="0" * 64)
        result = signer.verify(tampered, self.VERIFICATION)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "signature_invalid")
        self.assertFalse(result["signature_valid"])

    def test_unknown_key_reported(self) -> None:
        anchor = AuditAnchorSigner(LocalKeyProvider("other-secret")).sign(self.VERIFICATION)
        result = AuditAnchorSigner(LocalKeyProvider("anchor-secret")).verify(anchor, self.VERIFICATION)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "unknown_key")

    def test_rotated_provider_accepts_old_anchor(self) -> None:
        old = EnvKeyProvider(b"A" * 32)
        anchor = AuditAnchorSigner(old).sign(self.VERIFICATION)
        rotated = AuditAnchorSigner(EnvKeyProvider(b"B" * 32, previous=b"A" * 32))
        self.assertTrue(rotated.verify(anchor, self.VERIFICATION)["valid"])

    def test_invalid_chain_is_not_signed(self) -> None:
        signer = AuditAnchorSigner(LocalKeyProvider("anchor-secret"))
        with self.assertRaises(KmsError):
            signer.sign({"valid": False, "head": "", "count": 0})

    def test_unsupported_version_rejected(self) -> None:
        signer = AuditAnchorSigner(LocalKeyProvider("anchor-secret"))
        anchor = replace(signer.sign(self.VERIFICATION), version=99)
        self.assertEqual(signer.verify(anchor, self.VERIFICATION)["reason"], "unsupported_anchor_version")

    def test_key_material_has_no_secret_in_repr(self) -> None:
        material = LocalKeyProvider("anchor-secret").current("audit-anchor")
        self.assertNotIn(material.key.hex(), repr(material))


if __name__ == "__main__":
    unittest.main()
