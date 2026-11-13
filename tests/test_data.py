"""آزمون داده: اعتبارسنجی، کیفیت، قرنطینه و نسخه‌بندی."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fxars.core.errors import DataInvalidError
from fxars.core.timeutil import format_ts
from fxars.data.providers import read_candle_csv, write_candle_csv
from fxars.data.quality import DataQualityEngine
from fxars.data.reconciliation import match_candles
from fxars.data.snapshot import candles_digest, snapshot_id
from fxars.data.validation import CandleValidator
from fxars.domain.enums import QualityStatus
from fxars.domain.models import DataSource
from fxars.instruments.calendar import (
    TradingCalendar,
    default_early_closes,
    default_holidays,
    default_metal_holidays,
)

from tests.helpers import make_env

UTC = UTC


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
        self.assertEqual(assessment.status, QualityStatus.INVALID)

    def test_daily_bar_aligned_to_session_open_is_valid(self) -> None:
        calendar = TradingCalendar(default_holidays())
        daily = replace(
            self.candle, timeframe="D1",
            open_time=datetime(2026, 11, 3, 22, tzinfo=UTC),
            available_at=datetime(2026, 11, 4, 22, tzinfo=UTC),
            ingested_at=datetime(2026, 11, 4, 22, tzinfo=UTC),
        )
        assessment = CandleValidator(self.env.instrument, calendar=calendar).assess(daily)
        self.assertNotIn("misaligned_bar", assessment.flags)
        self.assertEqual(assessment.status, QualityStatus.VALID)

    def test_daily_bar_at_utc_midnight_is_soft_misaligned(self) -> None:
        calendar = TradingCalendar(default_holidays())
        daily = replace(
            self.candle, timeframe="D1",
            open_time=datetime(2026, 11, 3, 0, tzinfo=UTC),
            available_at=datetime(2026, 11, 4, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 11, 4, 0, tzinfo=UTC),
        )
        assessment = CandleValidator(self.env.instrument, calendar=calendar).assess(daily)
        self.assertIn("misaligned_bar", assessment.flags)
        self.assertEqual(assessment.status, QualityStatus.SUSPECT)

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

    def test_run_reports_explicit_expected_counts(self) -> None:
        candles = self.env.candles[:120]
        run = self.engine.evaluate(
            instrument=self.instrument, timeframe="H1", source_id="test",
            candles=candles, now=candles[-1].available_at,
        )
        self.assertEqual(run.expected, 120)
        self.assertEqual(run.matched, 120)
        self.assertEqual(run.extra, 0)
        self.assertEqual(run.latest_present_at, candles[-1].open_time)
        self.assertEqual(run.latest_expected_at, candles[-1].open_time)

    def test_run_roundtrip_keeps_match_fields(self) -> None:
        candles = self.env.candles[:120]
        run = self.engine.evaluate(
            instrument=self.instrument, timeframe="H1", source_id="test",
            candles=candles, now=candles[-1].available_at,
        )
        self.env.platform.quality_runs.save(run)
        loaded = self.env.platform.quality_runs.get(run.run_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.to_dict(), run.to_dict())

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


class DataQualitySettingsTests(unittest.TestCase):
    def test_defaults_are_explicit(self) -> None:
        from fxars.config.settings import DataQualitySettings

        settings = DataQualitySettings()
        self.assertEqual(settings.max_spread_pips, Decimal("20"))
        self.assertEqual(settings.max_price_jump_pips, Decimal("250"))

    def test_thresholds_are_configurable(self) -> None:
        from fxars.config.settings import Settings

        settings = Settings.from_dict({
            "db_path": ":memory:",
            "data_quality": {"max_spread_pips": "4.5", "max_price_jump_pips": "80"},
        })
        self.assertEqual(settings.data_quality.max_spread_pips, Decimal("4.5"))
        self.assertEqual(settings.data_quality.max_price_jump_pips, Decimal("80"))


class QualityPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)
        self.instrument = self.env.instrument
        self.pip = self.instrument.pip_size
        self.base_settings = self.env.platform.quality.settings

    def tearDown(self) -> None:
        self.env.close()

    def _engine(self, **overrides):
        return DataQualityEngine(replace(self.base_settings, **overrides), self.env.platform.calendar)

    def _evaluate(self, engine, candles):
        return engine.evaluate(
            instrument=self.instrument, timeframe="H1", source_id="test",
            candles=list(candles), now=candles[-1].available_at,
        )

    def test_spread_threshold_comes_from_settings(self) -> None:
        candles = list(self.env.candles[:60])
        spread = self.pip * Decimal("10")
        candles[20] = replace(candles[20], spread=spread)

        strict = self._evaluate(self._engine(max_spread_pips=Decimal("5")), candles)
        self.assertGreater(strict.suspect, 0)
        self.assertEqual(strict.verdict, "WARN")
        self.assertTrue(any(
            "spread_anomaly" in issue.details.get("flags", ())
            for issue in strict.issues if issue.rule == "candle_quality"
        ))

        relaxed = self._evaluate(self._engine(max_spread_pips=Decimal("30")), candles)
        self.assertEqual(relaxed.suspect, 0)
        self.assertEqual(relaxed.verdict, "PASS")

    def test_price_jump_threshold_comes_from_settings(self) -> None:
        candles = list(self.env.candles[:60])
        previous = candles[19]
        close = previous.close + self.pip * Decimal("100")
        candles[20] = replace(
            candles[20], close=close,
            high=max(candles[20].high, close), low=min(candles[20].low, close),
        )

        def has_jump_flag(run) -> bool:
            return any(
                "price_jump" in issue.details.get("flags", ())
                for issue in run.issues if issue.rule == "candle_quality"
            )

        strict = self._evaluate(self._engine(max_price_jump_pips=Decimal("50")), candles)
        self.assertTrue(has_jump_flag(strict))

        relaxed = self._evaluate(self._engine(max_price_jump_pips=Decimal("250")), candles)
        self.assertFalse(has_jump_flag(relaxed))


class DataSourceTests(unittest.TestCase):
    def _source(self, **overrides) -> DataSource:
        payload = {
            "source_id": "primary",
            "name": "Primary Feed",
            "kind": "broker",
            "license_id": "terms",
            "redistribution_allowed": False,
            "retention_days": 365,
            "timezone": "UTC",
        }
        payload.update(overrides)
        return DataSource(**payload)

    def test_valid_timezone_is_accepted(self) -> None:
        self.assertEqual(self._source(timezone="Europe/London").timezone, "Europe/London")
        self.assertEqual(self._source(timezone="Asia/Tokyo").timezone, "Asia/Tokyo")

    def test_invalid_timezone_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._source(timezone="Mars/Olympus")
        with self.assertRaises(ValueError):
            self._source(timezone="   ")

    def test_non_positive_retention_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._source(retention_days=0)
        with self.assertRaises(ValueError):
            self._source(retention_days=-30)

    def test_empty_source_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._source(source_id="  ")


class MatchReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=240)
        self.calendar = self.env.calendar

    def tearDown(self) -> None:
        self.env.close()

    def _match(self, candles, timeframe: str = "H1"):
        return match_candles(
            candles, instrument_id="EURUSD", timeframe=timeframe, source_id="demo_feed",
            calendar=self.calendar, now=self.env.clock(),
        )

    def test_complete_series_matches_all_expected_bars(self) -> None:
        report = self._match(self.env.candles[:120])
        self.assertEqual(report.expected, 120)
        self.assertEqual(report.present, 120)
        self.assertEqual(report.matched, 120)
        self.assertEqual((report.missing, report.extra, report.duplicates), (0, 0, 0))
        self.assertTrue(report.ok)
        self.assertEqual(report.latest_present_at, self.env.candles[119].open_time)
        self.assertEqual(
            report.latest_expected_at,
            self.calendar.last_closed_bar_time(self.env.clock(), "H1"),
        )

    def test_missing_bar_is_reported_by_timestamp(self) -> None:
        candles = list(self.env.candles[:120])
        removed = candles.pop(60)
        report = self._match(candles)
        self.assertEqual(report.missing, 1)
        self.assertEqual(report.missing_times, (removed.open_time,))
        self.assertEqual(report.matched, report.expected - 1)
        self.assertFalse(report.ok)

    def test_off_grid_bar_is_reported_as_extra(self) -> None:
        candles = list(self.env.candles[:120])
        saturday = datetime(2026, 2, 7, 12, tzinfo=UTC)
        off_grid = replace(
            candles[10], open_time=saturday,
            available_at=saturday + timedelta(hours=1),
            ingested_at=saturday + timedelta(hours=1),
        )
        report = self._match(candles + [off_grid])
        self.assertEqual(report.extra, 1)
        self.assertEqual(report.extra_times, (saturday,))
        self.assertEqual(report.matched, report.expected)

    def test_duplicate_timestamps_are_counted(self) -> None:
        candles = list(self.env.candles[:120])
        candles.append(candles[30])
        report = self._match(candles)
        self.assertEqual(report.duplicates, 1)
        self.assertEqual(report.present, 120)
        self.assertFalse(report.ok)


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

    def test_repeated_quarantine_of_same_bar_keeps_one_row(self) -> None:
        broken = replace(self.env.candles[50], high=self.env.candles[50].low - Decimal("0.01"))
        for _ in range(3):
            result = self.env.platform.ingestion.ingest(
                [broken], instrument_id="EURUSD", source_id="demo_feed", now=self.env.clock(),
            )
            self.assertEqual(result.quarantined, 1)
        rows = self.env.platform.db.query(
            "SELECT id, created_at FROM candle_quarantine WHERE instrument_id='EURUSD' "
            "AND source_id='demo_feed' AND open_time=?",
            (format_ts(broken.open_time),),
        )
        self.assertEqual(len(rows), 1)

    def test_quarantine_row_reflects_latest_payload(self) -> None:
        key = ("EURUSD", "demo_feed", "H1")
        first = replace(self.env.candles[60], high=self.env.candles[60].low - Decimal("0.01"))
        self.env.platform.ingestion.ingest(
            [first], instrument_id=key[0], source_id=key[1], now=self.env.clock(),
        )
        before = self.env.platform.db.query_one(
            "SELECT id, created_at, payload FROM candle_quarantine "
            "WHERE instrument_id=? AND source_id=? AND timeframe=? AND open_time=?",
            (*key, format_ts(first.open_time)),
        )
        second = replace(first, low=first.high + Decimal("0.005"))
        self.env.platform.ingestion.ingest(
            [second], instrument_id=key[0], source_id=key[1], now=self.env.clock(),
        )
        after = self.env.platform.db.query_one(
            "SELECT id, created_at, payload FROM candle_quarantine "
            "WHERE instrument_id=? AND source_id=? AND timeframe=? AND open_time=?",
            (*key, format_ts(second.open_time)),
        )
        self.assertEqual(after["id"], before["id"])
        self.assertEqual(after["created_at"], before["created_at"])
        self.assertNotEqual(after["payload"], before["payload"])

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

    def test_identical_in_batch_duplicate_is_collapsed(self) -> None:
        candle = self.env.candles[40]
        result = self.env.platform.ingestion.ingest(
            [candle, candle], instrument_id="EURUSD", source_id="demo_feed", now=self.env.clock(),
        )
        self.assertEqual(result.accepted, 1)
        self.assertEqual(result.duplicates, 2)  # یکی در دسته، یکی در برابر نسخه ذخیره‌شده
        self.assertEqual(result.conflicts, 0)
        self.assertEqual(result.quarantined, 0)

    def test_conflicting_duplicate_is_quarantined(self) -> None:
        first = self.env.candles[30]
        close = first.close + Decimal("0.00100")
        conflicting = replace(
            first, close=close,
            high=max(first.high, close), low=min(first.low, close),
        )
        result = self.env.platform.ingestion.ingest(
            [first, conflicting], instrument_id="EURUSD", source_id="demo_feed", now=self.env.clock(),
        )
        self.assertEqual(result.accepted, 1)
        self.assertEqual(result.conflicts, 1)
        self.assertEqual(result.duplicates, 2)  # یکی در دسته، یکی در برابر نسخه ذخیره‌شده
        self.assertEqual(result.quarantined, 1)
        self.assertEqual(result.quality.verdict, "WARN")
        self.assertTrue(any(
            issue.rule == "conflicting_duplicate_timestamp" for issue in result.quality.issues
        ))
        stored = [
            candle for candle in self.env.platform.candles.range("EURUSD", "H1")
            if candle.open_time == first.open_time
        ]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].close, first.close)
        reasons = self.env.platform.db.scalar(
            "SELECT reasons FROM candle_quarantine ORDER BY id DESC LIMIT 1",
        )
        self.assertIn("conflicting_duplicate_timestamp", reasons)

    def test_ingestion_uses_quality_policy_spread_threshold(self) -> None:
        engine = self.env.platform.ingestion.quality
        engine.settings = replace(engine.settings, max_spread_pips=Decimal("5"))
        candle = replace(self.env.candles[70], spread=self.env.instrument.pip_size * Decimal("10"))
        result = self.env.platform.ingestion.ingest(
            [candle], instrument_id="EURUSD", source_id="demo_feed", now=self.env.clock(),
        )
        self.assertEqual(result.accepted, 1)
        stored = [
            item for item in self.env.platform.candles.range("EURUSD", "H1")
            if item.open_time == candle.open_time
        ][-1]
        self.assertEqual(stored.quality_status, QualityStatus.SUSPECT)
        self.assertIn("spread_anomaly", stored.quality_flags)

    def test_unregistered_source_is_rejected(self) -> None:
        with self.assertRaises(DataInvalidError):
            self.env.platform.ingestion.ingest(
                [self.env.candles[5]], instrument_id="EURUSD", source_id="ghost_feed", now=self.env.clock(),
            )
        count = self.env.platform.db.scalar(
            "SELECT COUNT(*) FROM candles WHERE source_id='ghost_feed'",
        )
        self.assertEqual(int(count), 0)

    def test_candle_source_must_match_request(self) -> None:
        with self.assertRaises(DataInvalidError):
            self.env.platform.ingestion.ingest(
                [self.env.candles[5]], instrument_id="EURUSD", source_id="demo_ref", now=self.env.clock(),
            )

    def test_bootstrap_registers_mt5_source(self) -> None:
        source = self.env.platform.instruments.get_source("mt5")
        self.assertIsNotNone(source)
        self.assertEqual(source.timezone, "UTC")
        self.assertGreater(source.retention_days, 0)

    def test_snapshot_id_stable(self) -> None:
        candles = self.env.candles[:100]
        first = snapshot_id(candles, "EURUSD", "H1")
        second = snapshot_id(list(candles), "EURUSD", "H1")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("snap_"))
        self.assertEqual(candles_digest(candles), candles_digest(list(candles)))


class TradingCalendarDstTests(unittest.TestCase):
    """مرز هفته باید با ساعت نیویورک محاسبه شود، نه ساعت ثابت UTC."""

    def setUp(self) -> None:
        self.calendar = TradingCalendar(
            default_holidays(),
            early_closes=default_early_closes(),
            metal_holidays=default_metal_holidays(),
        )

    def test_winter_week_boundaries_follow_new_york_close(self) -> None:
        # جمعه ۶ نوامبر ۲۰۲۶ (EST): آخرین کندل ساعت ۲۱:۰۰ UTC باز می‌شود و بازار ۲۲:۰۰ UTC بسته است.
        self.assertTrue(self.calendar.is_market_open(datetime(2026, 11, 6, 21, tzinfo=UTC)))
        self.assertFalse(self.calendar.is_market_open(datetime(2026, 11, 6, 22, tzinfo=UTC)))
        # یکشنبه ۸ نوامبر ۲۰۲۶ (EST): توقف ۱۵ دقیقه‌ای ۱۷:۰۰–۱۷:۱۵ نیویورک.
        self.assertFalse(self.calendar.is_market_open(datetime(2026, 11, 8, 21, tzinfo=UTC)))
        self.assertFalse(self.calendar.is_market_open(datetime(2026, 11, 8, 22, tzinfo=UTC)))
        self.assertTrue(self.calendar.is_market_open(datetime(2026, 11, 8, 22, 15, tzinfo=UTC)))

    def test_summer_week_boundaries_follow_new_york_close(self) -> None:
        # جمعه ۱۰ ژوئیه ۲۰۲۶ (EDT): بازار ۲۱:۰۰ UTC بسته می‌شود.
        self.assertTrue(self.calendar.is_market_open(datetime(2026, 7, 10, 20, tzinfo=UTC)))
        self.assertFalse(self.calendar.is_market_open(datetime(2026, 7, 10, 21, tzinfo=UTC)))
        # یکشنبه ۱۲ ژوئیه ۲۰۲۶ (EDT): توقف ۱۷:۰۰–۱۷:۱۵ نیویورک = ۲۱:۰۰–۲۱:۱۵ UTC.
        self.assertFalse(self.calendar.is_market_open(datetime(2026, 7, 12, 20, tzinfo=UTC)))
        self.assertFalse(self.calendar.is_market_open(datetime(2026, 7, 12, 21, tzinfo=UTC)))
        self.assertTrue(self.calendar.is_market_open(datetime(2026, 7, 12, 21, 15, tzinfo=UTC)))

    def test_expected_bars_match_winter_weekend(self) -> None:
        times = self.calendar.expected_bar_times(
            datetime(2026, 11, 6, 20, tzinfo=UTC), datetime(2026, 11, 9, 1, tzinfo=UTC), "H1",
        )
        self.assertIn(datetime(2026, 11, 6, 21, tzinfo=UTC), times)
        self.assertNotIn(datetime(2026, 11, 6, 22, tzinfo=UTC), times)
        self.assertNotIn(datetime(2026, 11, 7, 12, tzinfo=UTC), times)
        self.assertNotIn(datetime(2026, 11, 8, 21, tzinfo=UTC), times)
        self.assertIn(datetime(2026, 11, 8, 22, tzinfo=UTC), times)
        self.assertIn(datetime(2026, 11, 9, 0, tzinfo=UTC), times)

    def test_daily_grid_is_anchored_to_session_open(self) -> None:
        # کندل روزانه بروکر: نیمه‌شب وقت سرور = ۲۲:۰۰ UTC زمستان.
        winter = datetime(2026, 11, 3, 22, tzinfo=UTC)
        self.assertEqual(self.calendar.bar_floor(winter, "D1"), winter)
        self.assertTrue(self.calendar.is_aligned_bar(winter, "D1"))
        self.assertFalse(self.calendar.is_aligned_bar(datetime(2026, 11, 3, 0, tzinfo=UTC), "D1"))
        # تابستان: ۲۱:۰۰ UTC.
        summer = datetime(2026, 7, 8, 21, tzinfo=UTC)
        self.assertEqual(self.calendar.bar_floor(summer, "D1"), summer)

    def test_h4_grid_follows_session_open(self) -> None:
        for hour in (21, 1, 5, 9, 13, 17):
            moment = datetime(2026, 7, 8, hour, tzinfo=UTC)
            self.assertEqual(self.calendar.bar_floor(moment, "H4"), moment, hour)
        # هفتهٔ اختلاف DST: کندل ۲۲:۰۰ یک ساعت از شبکهٔ نیویورک جلوتر است و مجاز شمرده می‌شود.
        self.assertEqual(
            self.calendar.bar_floor(datetime(2026, 10, 27, 22, tzinfo=UTC), "H4"),
            datetime(2026, 10, 27, 21, tzinfo=UTC),
        )
        self.assertTrue(self.calendar.is_aligned_bar(datetime(2026, 10, 27, 22, tzinfo=UTC), "H4"))
        self.assertFalse(self.calendar.is_aligned_bar(datetime(2026, 10, 27, 23, tzinfo=UTC), "H4"))

    def test_expected_daily_bars_exclude_friday_session_open(self) -> None:
        times = self.calendar.expected_bar_times(
            datetime(2026, 11, 1, 22, tzinfo=UTC), datetime(2026, 11, 6, 22, tzinfo=UTC), "D1",
        )
        self.assertEqual(times, [
            datetime(2026, 11, 1, 22, tzinfo=UTC),
            datetime(2026, 11, 2, 22, tzinfo=UTC),
            datetime(2026, 11, 3, 22, tzinfo=UTC),
            datetime(2026, 11, 4, 22, tzinfo=UTC),
            datetime(2026, 11, 5, 22, tzinfo=UTC),
        ])


class TradingCalendarDowntimeTests(unittest.TestCase):
    """توقف روزانهٔ بروکر، تعطیلی زودتر و روز معاملاتی."""

    def setUp(self) -> None:
        self.calendar = TradingCalendar(
            default_holidays(),
            early_closes=default_early_closes(),
            metal_holidays=default_metal_holidays(),
        )

    def test_trading_date_flips_at_new_york_session_open(self) -> None:
        self.assertEqual(self.calendar.trading_date(datetime(2026, 11, 8, 21, tzinfo=UTC)), date(2026, 11, 8))
        self.assertEqual(self.calendar.trading_date(datetime(2026, 11, 8, 22, tzinfo=UTC)), date(2026, 11, 9))

    def test_trading_day_start_is_session_open_of_previous_new_york_day(self) -> None:
        # ۶ نوامبر ۲۰۲۶ در نیویورک هنوز EST است: ۱۷:۰۰ = ۲۲:۰۰ UTC.
        self.assertEqual(
            self.calendar.trading_day_start(datetime(2026, 11, 6, 10, 0, tzinfo=UTC)),
            datetime(2026, 11, 5, 22, 0, tzinfo=UTC),
        )
        # بعد از مرز، روز معاملاتی بعد آغاز می‌شود.
        self.assertEqual(
            self.calendar.trading_day_start(datetime(2026, 11, 6, 23, 0, tzinfo=UTC)),
            datetime(2026, 11, 6, 22, 0, tzinfo=UTC),
        )
        # سشن یکشنبه‌شب UTC (۲۲:۰۰) متعلق به دوشنبه است و از همان لحظه آغاز می‌شود.
        self.assertEqual(
            self.calendar.trading_day_start(datetime(2026, 11, 9, 1, 0, tzinfo=UTC)),
            datetime(2026, 11, 8, 22, 0, tzinfo=UTC),
        )

    def test_forex_downtime_skips_the_m15_bar_at_session_boundary(self) -> None:
        # چهارشنبه ۴ نوامبر ۲۰۲۶ (EST): ۲۲:۰۰ UTC = ۱۷:۰۰ نیویورک.
        boundary = datetime(2026, 11, 4, 22, 0, tzinfo=UTC)
        self.assertFalse(self.calendar.is_market_open(boundary))
        self.assertTrue(self.calendar.is_market_open(boundary.replace(minute=15)))
        self.assertFalse(self.calendar.is_bar_expected(boundary, "M15"))
        self.assertTrue(self.calendar.is_bar_expected(boundary.replace(minute=15), "M15"))
        # کندل‌های M30/H1 که از توقف عبور می‌کنند و در بازار باز بسته می‌شوند انتظار می‌روند.
        self.assertTrue(self.calendar.is_bar_expected(boundary, "M30"))
        self.assertTrue(self.calendar.is_bar_expected(boundary, "H1"))

    def test_metals_downtime_is_one_hour(self) -> None:
        boundary = datetime(2026, 11, 4, 22, 0, tzinfo=UTC)
        self.assertFalse(self.calendar.is_market_open(boundary, instrument_id="XAUUSD"))
        self.assertFalse(self.calendar.is_market_open(boundary, instrument_id="EURUSD"))
        mid_break = boundary.replace(minute=30)
        self.assertFalse(self.calendar.is_market_open(mid_break, instrument_id="XAUUSD"))
        self.assertTrue(self.calendar.is_market_open(mid_break, instrument_id="EURUSD"))
        self.assertFalse(self.calendar.is_bar_expected(boundary, "H1", instrument_id="XAUUSD"))
        self.assertTrue(self.calendar.is_bar_expected(boundary, "H1", instrument_id="EURUSD"))
        self.assertFalse(self.calendar.is_bar_expected(mid_break, "M30", instrument_id="XAUUSD"))
        self.assertTrue(self.calendar.is_bar_expected(boundary.replace(hour=23), "H1", instrument_id="XAUUSD"))
        # کندلی که دقیقاً در شروع توقف بسته می‌شود حذف نمی‌شود.
        self.assertTrue(self.calendar.is_bar_expected(boundary.replace(hour=21), "H1", instrument_id="XAUUSD"))

    def test_holidays_use_trading_date_and_keep_reopen_sessions(self) -> None:
        times = self.calendar.expected_bar_times(
            datetime(2025, 12, 21, 22, tzinfo=UTC), datetime(2025, 12, 31, 22, tzinfo=UTC), "D1",
        )
        self.assertEqual(times, [
            datetime(2025, 12, 21, 22, tzinfo=UTC),
            datetime(2025, 12, 22, 22, tzinfo=UTC),
            datetime(2025, 12, 23, 22, tzinfo=UTC),
            datetime(2025, 12, 25, 22, tzinfo=UTC),
            datetime(2025, 12, 28, 22, tzinfo=UTC),
            datetime(2025, 12, 29, 22, tzinfo=UTC),
            datetime(2025, 12, 30, 22, tzinfo=UTC),
        ])

    def test_early_close_stops_the_new_york_afternoon(self) -> None:
        # جمعه ۳ ژوئیه ۲۰۲۶ (EDT): بستن زودتر از موعد ساعت ۱۳:۰۰ نیویورک.
        times = self.calendar.expected_bar_times(
            datetime(2026, 7, 3, 16, tzinfo=UTC), datetime(2026, 7, 3, 20, tzinfo=UTC), "H1",
        )
        self.assertEqual(times, [datetime(2026, 7, 3, 16, tzinfo=UTC)])
        self.assertFalse(self.calendar.is_market_open(datetime(2026, 7, 3, 17, tzinfo=UTC)))
        # عصر روز قبل (آغاز سشن روز معاملاتی) تعطیل نیست.
        self.assertTrue(self.calendar.is_bar_expected(datetime(2026, 7, 2, 21, tzinfo=UTC), "H1"))

    def test_good_friday_closes_metals_but_not_forex(self) -> None:
        # کندل روزانه‌ای که ساعت ۱۷:۰۰ پنجشنبه ۲ آپریل ۲۰۲۶ باز می‌شود، سشن جمعهٔ مقدس است.
        bar = datetime(2026, 4, 2, 21, tzinfo=UTC)
        self.assertTrue(self.calendar.is_bar_expected(bar, "D1"))
        self.assertTrue(self.calendar.is_bar_expected(bar, "D1", instrument_id="EURUSD"))
        self.assertFalse(self.calendar.is_bar_expected(bar, "D1", instrument_id="XAUUSD"))
        self.assertTrue(self.calendar.is_bar_expected(
            datetime(2026, 4, 1, 21, tzinfo=UTC), "D1", instrument_id="XAUUSD",
        ))

    def test_reference_time_during_downtime_is_the_last_open_minute(self) -> None:
        reference = self.calendar.reference_time(datetime(2026, 11, 4, 22, 5, tzinfo=UTC))
        self.assertEqual(reference, datetime(2026, 11, 4, 21, 59, tzinfo=UTC))


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
