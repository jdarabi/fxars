"""آزمون داده: اعتبارسنجی، کیفیت، قرنطینه و نسخه‌بندی."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fxars.data.providers import read_candle_csv, write_candle_csv
from fxars.data.quality import DataQualityEngine
from fxars.data.snapshot import candles_digest, snapshot_id
from fxars.data.synthetic import generate_candles
from fxars.data.validation import CandleValidator
from fxars.domain.enums import QualityStatus
from fxars.instruments.calendar import TradingCalendar, default_holidays
from tests.helpers import make_env

UTC = timezone.utc


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)
        self.candle = self.env.candles[100]

    def tearDown(self) -> None:
        self.env.close()

    def test_valid_candle(self) -> None:
        assessment = CandleValidator(self.env.instrument).assess(self.candle)
        self.assertEqual(assessment.status, QualityStatus.VALID)

    def test_invalid_ohlc(self) -> None:
        broken = replace(self.candle, high=self.candle.low - Decimal("0.001"))
        assessment = CandleValidator(self.env.instrument).assess(broken)
        self.assertEqual(assessment.status, QualityStatus.INVALID)
        self.assertIn("high_below_low", assessment.flags)

    def test_negative_price(self) -> None:
        broken = replace(self.candle, low=Decimal("-1"))
        assessment = CandleValidator(self.env.instrument).assess(broken)
        self.assertEqual(assessment.status, QualityStatus.INVALID)

    def test_misaligned_bar(self) -> None:
        broken = replace(self.candle, open_time=self.candle.open_time + timedelta(minutes=5))
        assessment = CandleValidator(self.env.instrument).assess(broken)
        self.assertIn("misaligned_bar", assessment.flags)

    def test_unclosed_is_suspect(self) -> None:
        assessment = CandleValidator(self.env.instrument).assess(replace(self.candle, is_closed=False))
        self.assertEqual(assessment.status, QualityStatus.SUSPECT)


class QualityTests(unittest.TestCase):
    def setUp(self) -> None:
        from fxars.config.settings import Settings

        self.calendar = TradingCalendar(default_holidays())
        self.settings = Settings.from_dict({"db_path": ":memory:"})
        self.env = make_env(bars=240)
        self.engine = DataQualityEngine(self.settings.data_quality, self.calendar)
        self.instrument = self.env.instrument

    def tearDown(self) -> None:
        self.env.close()

    def test_clean_series_passes(self) -> None:
        run = self.engine.evaluate(
            instrument=self.instrument, timeframe="H1", source_id="test",
            candles=self.env.candles[:120], now=self.env.candles[119].available_at,
        )
        self.assertEqual(run.verdict, "PASS")
        self.assertFalse(run.stale)
        self.assertEqual(run.missing, 0)

    def test_missing_candle_detected(self) -> None:
        candles = list(self.env.candles[:120])
        removed = [candles.pop(60), candles.pop(60)]
        run = self.engine.evaluate(
            instrument=self.instrument, timeframe="H1", source_id="test",
            candles=candles, now=candles[-1].available_at,
        )
        self.assertGreater(run.missing, 0)
        self.assertTrue(any(issue.rule == "missing_candles" for issue in run.issues))
        self.assertEqual(run.verdict, "WARN")
        _ = removed

    def test_duplicate_detected(self) -> None:
        candles = list(self.env.candles[:80])
        candles.append(candles[30])
        run = self.engine.evaluate(
            instrument=self.instrument, timeframe="H1", source_id="test",
            candles=candles, now=candles[-1].available_at,
        )
        self.assertTrue(any(issue.rule == "duplicate_timestamp" for issue in run.issues))

    def test_stale_data(self) -> None:
        candles = self.env.candles[:80]
        run = self.engine.evaluate(
            instrument=self.instrument, timeframe="H1", source_id="test",
            candles=candles, now=candles[-1].available_at + timedelta(hours=6),
        )
        self.assertTrue(run.stale)
        self.assertEqual(run.verdict, "FAIL")
        self.assertTrue(any(issue.rule == "stale_data" for issue in run.issues))

    def test_source_divergence(self) -> None:
        primary = self.env.candles[:60]
        reference = [replace(candle, close=candle.close + Decimal("0.0010"), high=candle.high + Decimal("0.0010"))
                     for candle in primary]
        run = self.engine.evaluate(
            instrument=self.instrument, timeframe="H1", source_id="primary",
            candles=primary, now=primary[-1].available_at, reference_candles=reference,
        )
        self.assertTrue(any(issue.rule == "source_divergence" for issue in run.issues))

    def test_invalid_candle_fails(self) -> None:
        candles = list(self.env.candles[:60])
        candles[10] = replace(candles[10], high=candles[10].low - Decimal("0.001"))
        run = self.engine.evaluate(
            instrument=self.instrument, timeframe="H1", source_id="test",
            candles=candles, now=candles[-1].available_at,
        )
        self.assertGreater(run.invalid, 0)
        self.assertEqual(run.verdict, "FAIL")


class IngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=400)

    def tearDown(self) -> None:
        self.env.close()

    def test_invalid_candle_quarantined_not_stored(self) -> None:
        broken_time = self.env.candles[50].open_time
        broken = replace(self.env.candles[50], high=self.env.candles[50].low - Decimal("0.01"))
        result = self.env.platform.ingestion.ingest(
            [broken], instrument_id="EURUSD", source_id="demo_feed", now=self.env.clock(),
        )
        self.assertEqual(result.quarantined, 1)
        self.assertEqual(result.accepted, 0)
        stored = [candle for candle in self.env.platform.candles.range("EURUSD", "H1") if candle.open_time == broken_time]
        self.assertEqual(len(stored), 1)
        self.assertNotEqual(stored[0].high, broken.high)
        quarantine = self.env.platform.db.scalar("SELECT COUNT(*) FROM candle_quarantine")
        self.assertGreaterEqual(int(quarantine), 1)

    def test_revision_created_on_change(self) -> None:
        original = self.env.candles[20]
        changed = replace(original, close=original.close + Decimal("0.00010"))
        result = self.env.platform.ingestion.ingest(
            [changed], instrument_id="EURUSD", source_id="demo_feed", now=self.env.clock(),
        )
        self.assertEqual(result.revised, 1)
        stored = [candle for candle in self.env.platform.candles.range("EURUSD", "H1")
                  if candle.open_time == original.open_time][0]
        self.assertEqual(stored.close, changed.close)
        self.assertEqual(stored.revision, 2)
        revisions = self.env.platform.db.scalar("SELECT COUNT(*) FROM candle_revision_log")
        self.assertEqual(int(revisions), 1)

    def test_identical_reingest_is_duplicate(self) -> None:
        result = self.env.platform.ingestion.ingest(
            [self.env.candles[1]], instrument_id="EURUSD", source_id="demo_feed", now=self.env.clock(),
        )
        self.assertEqual(result.duplicates, 1)
        self.assertEqual(result.revised, 0)

    def test_snapshot_id_stable(self) -> None:
        candles = self.env.candles[:100]
        first = snapshot_id(candles, "EURUSD", "H1")
        second = snapshot_id(list(candles), "EURUSD", "H1")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("snap_"))
        self.assertEqual(candles_digest(candles), candles_digest(list(candles)))


class CsvProviderTests(unittest.TestCase):
    def _path(self, name: str) -> Path:
        directory = Path("data") / "tmp_tests"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / name

    def test_roundtrip(self) -> None:
        env = make_env(bars=240)
        try:
            candles = env.candles[:10]
            path = self._path("candles_roundtrip.csv")
            write_candle_csv(candles, path)
            loaded = read_candle_csv(path, instrument_id="EURUSD", source_id="test", timeframe="H1",
                                     now=env.clock())
            self.assertEqual(len(loaded.candles), 10)
            self.assertEqual(loaded.candles[0].open, candles[0].open)
            self.assertEqual(loaded.candles[-1].close, candles[-1].close)
            self.assertEqual(loaded.errors, [])
        finally:
            env.close()

    def test_bad_row_reported(self) -> None:
        path = self._path("candles_bad.csv")
        path.write_text(
            "bar_open_time_utc,open,high,low,close\n"
            "2026-01-01T00:00:00Z,1.0,1.1,0.9,1.05\n"
            "not-a-date,1.0,1.1,0.9,1.05\n",
            encoding="utf-8",
        )
        loaded = read_candle_csv(path, instrument_id="EURUSD", source_id="test", timeframe="H1")
        self.assertEqual(len(loaded.candles), 1)
        self.assertEqual(len(loaded.errors), 1)


if __name__ == "__main__":
    unittest.main()
