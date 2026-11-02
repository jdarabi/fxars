"""Property-based tests using hypothesis.

Requires: pip install -e ".[test]"
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st
    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


def _decimals(min_value: str, max_value: str, places: int = 5):
    return st.decimals(
        min_value=Decimal(min_value),
        max_value=Decimal(max_value),
        places=places,
    )


def _utc_datetimes(start: str = "2020-01-01T00:00:00Z", end: str = "2030-01-01T00:00:00Z"):
    from fxars.core.timeutil import parse_ts
    return st.datetimes(
        min_value=parse_ts(start).replace(tzinfo=None),
        max_value=parse_ts(end).replace(tzinfo=None),
        timezones=st.just(timezone.utc),
    )


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis not installed")
class CoreNumericProperties(unittest.TestCase):
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @given(_decimals("0.0001", "1000000", 5))
    def test_quantize_is_idempotent(self, value):
        from fxars.core.numerics import quantize
        q1 = quantize(value, 2)
        q2 = quantize(q1, 2)
        self.assertEqual(q1, q2)
        self.assertLessEqual(abs(q1 - value), Decimal("0.005"))

    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @given(
        st.decimals(min_value=Decimal("0"), max_value=Decimal("1000000"), places=4),
        st.decimals(min_value=Decimal("0.01"), max_value=Decimal("1"), places=2),
    )
    def test_floor_to_step_is_lower_bound_and_multiple(self, value, step):
        from fxars.core.numerics import floor_to_step
        floored = floor_to_step(value, step)
        self.assertLessEqual(floored, value)
        if step > 0:
            ratio = floored / step
            self.assertEqual(ratio, ratio.to_integral_value(), f"ratio={ratio}")

    @settings(max_examples=100)
    @given(st.text(min_size=1, max_size=40))
    def test_stable_id_deterministic(self, payload):
        from fxars.core.ids import stable_id
        a = stable_id("x", payload)
        b = stable_id("x", payload)
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("x_"))

    @settings(max_examples=100)
    @given(st.dictionaries(
        st.text(min_size=1, max_size=10),
        st.one_of(st.integers(), st.text(max_size=20), st.booleans()),
        min_size=0, max_size=10,
    ))
    def test_canonical_json_is_stable_under_key_order(self, payload):
        from fxars.core.hashing import canonical_json
        reversed_payload = dict(reversed(list(payload.items())))
        self.assertEqual(canonical_json(payload), canonical_json(reversed_payload))


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis not installed")
class TimePropertyTests(unittest.TestCase):
    @settings(max_examples=200)
    @given(
        _utc_datetimes(),
        st.integers(min_value=-12 * 3600, max_value=14 * 3600),
    )
    def test_parse_format_roundtrip(self, moment, offset_seconds):
        from fxars.core.timeutil import format_ts, parse_ts
        moment = moment.replace(microsecond=0)
        text = format_ts(moment)
        parsed = parse_ts(text)
        self.assertEqual(parsed, moment)

        shifted = moment.astimezone(timezone(timedelta(seconds=offset_seconds)))
        self.assertEqual(parse_ts(shifted.isoformat()), moment)

    @settings(max_examples=200)
    @given(_utc_datetimes())
    def test_floor_to_timeframe_is_aligned(self, moment):
        from fxars.core.timeutil import floor_to_timeframe, timeframe_delta
        for tf in ("M5", "M15", "H1", "H4", "D1"):
            floored = floor_to_timeframe(moment, tf)
            delta = timeframe_delta(tf)
            self.assertLessEqual(floored, moment)
            offset = moment - floored
            self.assertGreaterEqual(offset, timedelta(0))
            self.assertLess(offset, delta)
            self.assertEqual(floored.microsecond, 0, f"floored has sub-second microsecond: {floored}")


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis not installed")
class CandleInvariantTests(unittest.TestCase):
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @given(
        st.decimals(min_value=Decimal("0.9"), max_value=Decimal("1.2"), places=5),
        st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("0.05"), places=5),
        st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("0.01"), places=5),
    )
    def test_digest_ignores_ingested_at(self, open_price, body, wick):
        from fxars.domain.models import Candle
        close = open_price + body
        high = max(open_price, close) + wick
        low = min(open_price, close) - wick
        common = dict(
            instrument_id="EURUSD", source_id="test", timeframe="H1",
            open_time=datetime(2026, 2, 2, 10, tzinfo=timezone.utc),
            open=open_price, high=high, low=low, close=close,
            available_at=datetime(2026, 2, 2, 11, 0, 30, tzinfo=timezone.utc),
        )
        a = Candle(ingested_at=datetime(2026, 2, 2, 11, 0, 31, tzinfo=timezone.utc), **common)
        b = Candle(ingested_at=datetime(2026, 2, 2, 11, 0, 32, tzinfo=timezone.utc), **common)
        self.assertEqual(a.digest(), b.digest())
        self.assertGreaterEqual(a.high, a.close)
        self.assertGreaterEqual(a.high, a.open)
        self.assertLessEqual(a.low, a.close)
        self.assertLessEqual(a.low, a.open)

    def test_available_before_open_rejected(self):
        from fxars.domain.models import Candle
        with self.assertRaises(ValueError):
            Candle(
                instrument_id="EURUSD", source_id="test", timeframe="H1",
                open_time=datetime(2026, 2, 2, 10, tzinfo=timezone.utc),
                open=Decimal("1.0850"), high=Decimal("1.0860"),
                low=Decimal("1.0840"), close=Decimal("1.0855"),
                ingested_at=datetime(2026, 2, 2, 11, tzinfo=timezone.utc),
                available_at=datetime(2026, 2, 2, 9, tzinfo=timezone.utc),
            )


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis not installed")
class SizingPropertyTests(unittest.TestCase):
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @given(
        st.decimals(min_value=Decimal("100"), max_value=Decimal("1000000"), places=2),
        st.decimals(min_value=Decimal("0.001"), max_value=Decimal("0.01"), places=4),
        st.decimals(min_value=Decimal("1.08"), max_value=Decimal("1.10"), places=5),
        st.decimals(min_value=Decimal("0.001"), max_value=Decimal("0.05"), places=5),
    )
    def test_sizing_loss_never_exceeds_risk(self, equity, risk_fraction, entry, stop_distance):
        from fxars.instruments.spec import default_instruments
        from fxars.risk.sizing import SizingInput, calculate_position_size

        eurusd = next(i for i in default_instruments() if i.instrument_id == "EURUSD")
        stop = entry - stop_distance
        if stop <= 0:
            return
        result = calculate_position_size(SizingInput(
            equity=equity,
            risk_fraction=risk_fraction,
            entry_price=entry,
            stop_price=stop,
            instrument=eurusd,
        ))
        if result.valid:
            tolerance = result.risk_amount * Decimal("0.02") + Decimal("1")
            self.assertLessEqual(
                result.estimated_loss_at_stop,
                result.risk_amount + tolerance,
                f"loss={result.estimated_loss_at_stop} risk={result.risk_amount}",
            )


if __name__ == "__main__":
    unittest.main()