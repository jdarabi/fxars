"""آزمون مدل دامنه: کندل، نماد، رویداد، سناریو."""

from __future__ import annotations

import unittest
from datetime import timedelta
from decimal import Decimal

from fxars.domain.enums import Direction, QualityStatus, ScenarioStatus
from fxars.domain.models import Candle, EconomicEvent, Instrument, PriceZone, Scenario


def sample_candle(**overrides) -> Candle:
    base = dict(
        instrument_id="EURUSD", source_id="test", timeframe="H1",
        open_time="2026-10-30T10:00:00Z", open="1.08500", high="1.08700",
        low="1.08400", close="1.08600", tick_volume=1000, spread="0.00012",
        is_closed=True, quality_status=QualityStatus.VALID,
        ingested_at="2026-10-30T11:00:01Z", available_at="2026-10-30T11:00:01Z",
    )
    base.update(overrides)
    return Candle(**base)


class PriceZoneTests(unittest.TestCase):
    def test_validation_and_helpers(self) -> None:
        zone = PriceZone(low="1.0850", high="1.0860")
        self.assertTrue(zone.contains(Decimal("1.0855")))
        self.assertFalse(zone.contains(Decimal("1.0870")))
        self.assertEqual(zone.width, Decimal("0.0010"))
        self.assertTrue(zone.overlaps(PriceZone("1.0855", "1.0870")))

    def test_invalid_zone(self) -> None:
        with self.assertRaises(ValueError):
            PriceZone(low="1.09", high="1.08")


class InstrumentTests(unittest.TestCase):
    def test_eurusd_spec(self) -> None:
        from fxars.instruments.spec import default_instruments

        instrument = [item for item in default_instruments() if item.instrument_id == "EURUSD"][0]
        self.assertEqual(instrument.pip_size, Decimal("0.0001"))
        self.assertEqual(instrument.contract_size, Decimal("100000"))
        self.assertEqual(instrument.round_price(Decimal("1.085123")), Decimal("1.08512"))
        self.assertTrue(instrument.is_valid_at(Candle(**{
            "instrument_id": "EURUSD", "source_id": "t", "timeframe": "H1",
            "open_time": "2026-10-30T10:00:00Z", "open": "1", "high": "1", "low": "1", "close": "1",
            "ingested_at": "2026-10-30T11:00:00Z", "available_at": "2026-10-30T11:00:00Z",
        }).open_time))

    def test_invalid_spec_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Instrument(
                instrument_id="X", symbol="X", base_currency="A", quote_currency="B", digits=2,
                point="0.01", pip_size="0", contract_size="1", min_lot="0.1", lot_step="0.1",
                max_lot="1", tick_size="0.01", tick_value="1", profit_currency="B",
                margin_rate="0.01", stop_level_points=0, freeze_level_points=0,
                swap_long="0", swap_short="0", commission_per_lot="0",
            )


class CandleTests(unittest.TestCase):
    def test_derived_values(self) -> None:
        candle = sample_candle()
        self.assertEqual(candle.close_time, candle.open_time + timedelta(hours=1))
        self.assertEqual(candle.range, Decimal("0.00300"))
        self.assertEqual(candle.body, Decimal("0.00100"))
        self.assertEqual(candle.upper_wick, Decimal("0.00100"))
        self.assertTrue(candle.bullish)

    def test_availability_must_not_precede_open(self) -> None:
        with self.assertRaises(ValueError):
            sample_candle(available_at="2026-10-30T09:00:00Z")

    def test_digest_ignores_ingested_at(self) -> None:
        first = sample_candle()
        second = sample_candle(ingested_at="2026-10-30T12:00:00Z")
        self.assertEqual(first.digest(), second.digest())

    def test_digest_changes_with_price(self) -> None:
        self.assertNotEqual(sample_candle().digest(), sample_candle(close="1.08610").digest())

    def test_contract_roundtrip(self) -> None:
        candle = sample_candle()
        restored = Candle.from_dict(candle.to_dict())
        self.assertEqual(restored.digest(), candle.digest())
        self.assertEqual(restored.open, candle.open)


class EventTests(unittest.TestCase):
    def test_surprise(self) -> None:
        event = EconomicEvent(
            event_id="e1", indicator="NFP", currency="USD", country="US",
            event_time="2026-10-30T12:30:00Z", published_at="2026-10-30T12:30:30Z",
            available_at="2026-10-30T12:32:00Z", importance="HIGH",
            actual="200", forecast="180", previous="170",
        )
        self.assertEqual(event.surprise, Decimal("20"))
        self.assertAlmostEqual(event.surprise_ratio, 20 / 180)
        self.assertTrue(event.in_window(event.event_time, 30, 30))
        self.assertFalse(event.in_window(event.event_time + timedelta(hours=2), 30, 30))

    def test_event_roundtrip(self) -> None:
        event = EconomicEvent(
            event_id="e1", indicator="CPI", currency="EUR", country="EU",
            event_time="2026-10-30T10:00:00Z", published_at=None,
            available_at="2026-10-30T10:02:00Z", importance="MEDIUM",
        )
        restored = EconomicEvent.from_dict(event.to_dict())
        self.assertEqual(restored.event_time, event.event_time)
        self.assertEqual(restored.event_id, "e1")


class ScenarioTests(unittest.TestCase):
    def _scenario(self) -> Scenario:
        return Scenario(
            scenario_id="sc_1", instrument_id="EURUSD", timeframe="H1", direction=Direction.LONG,
            status=ScenarioStatus.WATCH,
            entry_condition={"type": "price_cross_above", "level": "1.08500"},
            invalidation_condition={"type": "close_below", "level": "1.08000"},
            stop_logic={"type": "structure_low", "level": "1.08000"},
            target_logic=({"type": "rr_multiple", "value": 1.5, "price": "1.08750"},),
            expiry_at="2026-10-30T18:00:00Z", evidence_ids=("ev1",), analysis_run_id="ar_1",
            decision_explanation="test", created_at="2026-10-30T12:00:00Z",
            updated_at="2026-10-30T12:00:00Z", rules_version="v1", config_hash="h",
        )

    def test_stop_level_and_status(self) -> None:
        scenario = self._scenario()
        self.assertEqual(scenario.stop_level, Decimal("1.08000"))
        updated = scenario.with_status(ScenarioStatus.ARMED, when="2026-10-30T12:30:00Z")
        self.assertEqual(updated.status, ScenarioStatus.ARMED)
        self.assertEqual(scenario.status, ScenarioStatus.WATCH)

    def test_neutral_scenario_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Scenario(
                scenario_id="sc", instrument_id="EURUSD", timeframe="H1", direction=Direction.NEUTRAL,
                status=ScenarioStatus.DRAFT, entry_condition={}, invalidation_condition={},
                stop_logic={}, target_logic=(), expiry_at="2026-10-30T18:00:00Z", evidence_ids=(),
                analysis_run_id="ar", decision_explanation="", created_at="2026-10-30T12:00:00Z",
                updated_at="2026-10-30T12:00:00Z", rules_version="v1", config_hash="h",
            )


if __name__ == "__main__":
    unittest.main()
