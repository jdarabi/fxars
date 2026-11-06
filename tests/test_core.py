"""آزمون‌های پایه: زمان، Decimal، هش، شناسه و خطاها."""

from __future__ import annotations

import unittest
from datetime import UTC
from decimal import Decimal

from fxars.core.errors import FxarsError, RiskRejectedError
from fxars.core.hashing import canonical_json, sha256_obj
from fxars.core.ids import stable_id
from fxars.core.numerics import floor_to_step, quantize, to_decimal
from fxars.core.timeutil import format_ts, parse_ts


class TimeTests(unittest.TestCase):
    def test_parse_and_format_roundtrip(self) -> None:
        text = "2026-10-30T10:00:00Z"
        moment = parse_ts(text)
        self.assertEqual(moment.tzinfo, UTC)
        self.assertEqual(format_ts(moment), text)

    def test_naive_is_utc(self) -> None:
        moment = parse_ts("2026-10-30 10:00:00")
        self.assertEqual(moment.utcoffset().total_seconds(), 0)

    def test_offset_conversion(self) -> None:
        moment = parse_ts("2026-10-30T13:30:00+03:30")
        self.assertEqual(format_ts(moment), "2026-10-30T10:00:00Z")

    def test_invalid_timestamp(self) -> None:
        with self.assertRaises(ValueError):
            parse_ts("not-a-time")


class DecimalTests(unittest.TestCase):
    def test_decimal_from_string_preserves_precision(self) -> None:
        self.assertEqual(to_decimal("1.08500"), Decimal("1.08500"))

    def test_quantize_half_up(self) -> None:
        self.assertEqual(quantize("1.005", 2), Decimal("1.01"))

    def test_floor_to_step(self) -> None:
        self.assertEqual(floor_to_step(Decimal("0.087"), Decimal("0.01")), Decimal("0.08"))
        self.assertEqual(floor_to_step(Decimal("0.08"), Decimal("0.01")), Decimal("0.08"))

    def test_float_rejected_for_nonfinite(self) -> None:
        with self.assertRaises(ValueError):
            to_decimal(float("nan"))


class HashTests(unittest.TestCase):
    def test_canonical_json_is_stable(self) -> None:
        first = canonical_json({"b": 1, "a": Decimal("1.20")})
        second = canonical_json({"a": Decimal("1.20"), "b": 1})
        self.assertEqual(first, second)

    def test_sha256_obj_changes_with_content(self) -> None:
        self.assertNotEqual(sha256_obj({"a": 1}), sha256_obj({"a": 2}))

    def test_stable_id_deterministic(self) -> None:
        self.assertEqual(stable_id("x", "a", 1), stable_id("x", "a", 1))
        self.assertTrue(stable_id("x", "a").startswith("x_"))


class ErrorTests(unittest.TestCase):
    def test_error_contract(self) -> None:
        error = RiskRejectedError("رد شد", details={"reason": "X"})
        payload = error.to_dict()["error"]
        self.assertEqual(payload["code"], "RISK_REJECTED")
        self.assertEqual(payload["message"], "رد شد")
        self.assertEqual(error.http_status, 422)
        self.assertIsInstance(error, FxarsError)


if __name__ == "__main__":
    unittest.main()
