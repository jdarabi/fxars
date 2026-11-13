"""تست برنامه اصلاح زمان کندل‌های mt5 (dry-run)."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "repair_mt5_server_time", _ROOT / "scripts" / "repair_mt5_server_time.py",
)
repair = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = repair
_spec.loader.exec_module(repair)

_SCHEMA = """
CREATE TABLE candles (
    instrument_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open_time TEXT NOT NULL,
    revision INTEGER NOT NULL,
    is_closed INTEGER NOT NULL,
    quality_status TEXT NOT NULL,
    available_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (instrument_id, source_id, timeframe, open_time, revision)
);
"""


def _insert(conn, open_time: str, available_at: str, *, revision: int = 1,
            instrument: str = "EURUSD", timeframe: str = "H1") -> None:
    payload = json.dumps({
        "bar_open_time_utc": open_time,
        "available_at": available_at,
        "close_time_utc": available_at,
        "open": "1.1", "high": "1.2", "low": "1.0", "close": "1.15",
        "ingested_at": "2026-11-05T19:00:07Z",
        "instrument_id": instrument, "timeframe": timeframe,
        "source_id": "mt5", "revision": revision,
    })
    conn.execute(
        "insert into candles values (?, 'mt5', ?, ?, ?, 1, 'VALID', ?, '2026-11-05T19:00:07Z', ?)",
        (instrument, timeframe, open_time, revision, available_at, payload),
    )


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA)
    return conn


class RepairPlanTests(unittest.TestCase):
    def test_winter_and_summer_shift(self) -> None:
        conn = _make_conn()
        _insert(conn, "2026-11-06T23:00:00Z", "2026-11-07T00:00:00Z")   # +2
        _insert(conn, "2026-07-08T12:00:00Z", "2026-07-08T13:00:00Z")   # +3

        rows = repair._collect_plan_rows(conn, broker_timezone="Europe/Athens")
        by_old = {row.old_open: row for row in rows}

        winter = by_old["2026-11-06T23:00:00Z"]
        self.assertEqual(winter.new_open, "2026-11-06T21:00:00Z")
        self.assertEqual(winter.new_available, "2026-11-06T22:00:00Z")
        self.assertEqual(winter.shift_seconds, -7200)

        summer = by_old["2026-07-08T12:00:00Z"]
        self.assertEqual(summer.new_open, "2026-07-08T09:00:00Z")
        self.assertEqual(summer.shift_seconds, -10800)

        report = repair.build_plan(conn, broker_timezone="Europe/Athens")
        self.assertEqual(report["summary"]["total_rows"], 2)
        self.assertEqual(report["summary"]["shift_rows"], 2)
        self.assertEqual(report["summary"]["blocking_problems"], 0)
        self.assertEqual(report["shift_histogram_hours"]["H1"], {"-3": 1, "-2": 1})
        self.assertEqual(report["rebuild"], [])

    def test_daily_bar_shifts_to_previous_evening(self) -> None:
        conn = _make_conn()
        _insert(conn, "2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z", timeframe="D1")

        rows = repair._collect_plan_rows(conn, broker_timezone="Europe/Athens")
        self.assertEqual(rows[0].new_open, "2026-11-01T22:00:00Z")
        self.assertEqual(rows[0].new_available, "2026-11-02T22:00:00Z")

    def test_target_time_existing_in_old_set_is_not_a_collision(self) -> None:
        conn = _make_conn()
        _insert(conn, "2026-11-06T23:00:00Z", "2026-11-07T00:00:00Z")
        _insert(conn, "2026-11-06T21:00:00Z", "2026-11-06T22:00:00Z")

        report = repair.build_plan(conn, broker_timezone="Europe/Athens")

        # کل سری با هم جابه‌جا می‌شود؛ برخورد با برچسب قدیمیِ همان سری خطا نیست.
        self.assertEqual(report["summary"]["blocking_problems"], 0)
        self.assertEqual(report["problems"]["non_injective_groups"], [])

    def test_payload_mismatch_is_reported(self) -> None:
        conn = _make_conn()
        _insert(conn, "2026-11-06T23:00:00Z", "2026-11-07T00:00:00Z")
        conn.execute("update candles set payload = replace(payload, '\"bar_open_time_utc\": \"2026-11-06T23:00:00Z\"', '\"bar_open_time_utc\": \"2026-11-06T22:00:00Z\"')")

        report = repair.build_plan(conn, broker_timezone="Europe/Athens")

        self.assertEqual(report["summary"]["payload_mismatches"], 1)
        self.assertEqual(report["summary"]["blocking_problems"], 1)

    def test_rebuild_timeframe_is_excluded_from_shift_plan(self) -> None:
        conn = _make_conn()
        _insert(conn, "2026-11-06T23:00:00Z", "2026-11-07T00:00:00Z")
        _insert(conn, "2026-11-06T22:45:00Z", "2026-11-06T23:00:00Z", timeframe="M15")
        _insert(conn, "2026-11-06T22:45:00Z", "2026-11-06T23:00:00Z", timeframe="M15", revision=2)

        report = repair.build_plan(conn, broker_timezone="Europe/Athens")
        rows = repair._collect_plan_rows(conn, broker_timezone="Europe/Athens")

        self.assertEqual(report["summary"]["total_rows"], 3)
        self.assertEqual(report["summary"]["shift_rows"], 1)
        self.assertEqual(report["summary"]["rebuild_rows"], 2)
        self.assertEqual([row.timeframe for row in rows], ["H1"])
        self.assertEqual(len(report["rebuild"]), 1)
        rebuild_group = report["rebuild"][0]
        self.assertEqual(rebuild_group["instrument_id"], "EURUSD")
        self.assertEqual(rebuild_group["timeframe"], "M15")
        self.assertEqual(rebuild_group["rows"], 2)
        self.assertEqual(rebuild_group["groups"], 1)
        self.assertEqual(rebuild_group["revisions"], {"1": 1, "2": 1})
        self.assertEqual(report["rebuild_timeframes"], ["M15"])


class WallDstTests(unittest.TestCase):
    def test_fall_back_wall_is_ambiguous(self) -> None:
        tz = ZoneInfo("Europe/Athens")
        ambiguous, nonexistent = repair.wall_dst_flags(datetime(2026, 10, 25, 3, 0), tz)
        self.assertTrue(ambiguous)
        self.assertFalse(nonexistent)

    def test_spring_forward_wall_does_not_exist(self) -> None:
        tz = ZoneInfo("Europe/Athens")
        ambiguous, nonexistent = repair.wall_dst_flags(datetime(2026, 3, 29, 3, 0), tz)
        self.assertFalse(ambiguous)
        self.assertTrue(nonexistent)


class ApplyShiftTests(unittest.TestCase):
    def setUp(self) -> None:
        from fxars.storage.db import Database

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "fxars.db"
        db = Database(self.db_path)
        try:
            db.migrate()
        finally:
            db.close()
        conn = sqlite3.connect(self.db_path)
        try:
            _insert(conn, "2026-11-06T23:00:00Z", "2026-11-07T00:00:00Z")
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_apply_shift_moves_rows_and_logs(self) -> None:
        from fxars.storage.db import Database

        report, code = repair.apply_shift(
            self.db_path, broker_timezone="Europe/Athens", rebuild_timeframes=("M15",),
            backup_dir=self.root / "backups", actor="test",
        )

        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "applied")
        self.assertEqual(report["verification_issues"], [])
        self.assertTrue(report["audit_chain"]["valid"])
        self.assertTrue(Path(report["backup"]["path"]).exists())
        self.assertEqual(report["backup"]["mt5_rows"], 1)

        db = Database(self.db_path)
        try:
            row = db.query_one(
                "select open_time, available_at, payload from candles where source_id='mt5' and timeframe='H1'"
            )
            self.assertEqual(row["open_time"], "2026-11-06T21:00:00Z")
            self.assertEqual(row["available_at"], "2026-11-06T22:00:00Z")
            payload = json.loads(row["payload"])
            self.assertEqual(payload["bar_open_time_utc"], "2026-11-06T21:00:00Z")
            self.assertEqual(payload["available_at"], "2026-11-06T22:00:00Z")
            self.assertEqual(payload["close_time_utc"], "2026-11-06T22:00:00Z")

            log = db.query_one(
                "select open_time, reason from candle_revision_log where source_id='mt5' order by id desc limit 1"
            )
            self.assertEqual(log["open_time"], "2026-11-06T23:00:00Z")
            self.assertEqual(log["reason"], "timestamp_repair:2026-11-06T21:00:00Z")
            self.assertTrue(repair.AuditLog(db).verify()["valid"])
        finally:
            db.close()

    def test_apply_refuses_when_plan_is_blocking(self) -> None:
        from fxars.storage.db import Database

        db = Database(self.db_path)
        try:
            db.execute(
                "update candles set payload = replace(payload, '\"bar_open_time_utc\": \"2026-11-06T23:00:00Z\"', "
                "'\"bar_open_time_utc\": \"2026-11-06T22:00:00Z\"')"
            )
        finally:
            db.close()

        report, code = repair.apply_shift(
            self.db_path, broker_timezone="Europe/Athens", rebuild_timeframes=("M15",),
            backup_dir=self.root / "backups", actor="test",
        )

        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "refused")
        self.assertFalse((self.root / "backups").exists())
        db = Database(self.db_path)
        try:
            self.assertEqual(db.scalar("select open_time from candles where source_id='mt5'"),
                             "2026-11-06T23:00:00Z")
            self.assertEqual(db.scalar("select count(*) from candle_revision_log where source_id='mt5'"), 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
