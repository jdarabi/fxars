"""اصلاح زمان کندل‌های mt5: داده تاریخی به وقت سرور بروکر ذخیره شده، نه UTC.

حالت پیش‌فرض dry-run است و فقط می‌خواند؛ گزارش تفاوت‌ها را می‌نویسد.
با --apply جابه‌جایی زمانی (backup + تراکنش + revision log + audit) اجرا می‌شود.
با --apply-rebuild ردیف‌های تایم‌فریم‌های mixed (پیش‌فرض M15) از MT5 زنده بازسازی می‌شوند.

usage:
    python scripts/repair_mt5_server_time.py \
        --db data/fxars.db \
        --broker-timezone Europe/Athens \
        --report data/tmp_tests/mt5_time_repair_dryrun.json \
        --details data/tmp_tests/mt5_time_repair_dryrun.jsonl
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fxars.audit.audit import AuditAction, AuditLog  # noqa: E402
from fxars.audit.outbox import Outbox  # noqa: E402
from fxars.config.settings import Settings  # noqa: E402
from fxars.core.timeutil import format_ts, parse_ts  # noqa: E402
from fxars.data.ingestion import IngestionService  # noqa: E402
from fxars.data.quality import DataQualityEngine  # noqa: E402
from fxars.domain.enums import Timeframe  # noqa: E402
from fxars.domain.models import Candle  # noqa: E402
from fxars.instruments.calendar import (  # noqa: E402
    TradingCalendar,
    default_early_closes,
    default_holidays,
    default_metal_holidays,
)
from fxars.live.history import download_from_mt5  # noqa: E402
from fxars.storage.db import Database  # noqa: E402
from fxars.storage.repositories import (  # noqa: E402
    CandleRepository,
    DataQualityRepository,
    InstrumentRepository,
    RawPayloadRepository,
)

SOURCE_ID = "mt5"


@dataclass(frozen=True)
class PlannedRow:
    instrument_id: str
    timeframe: str
    revision: int
    old_open: str
    new_open: str
    old_available: str
    new_available: str
    shift_seconds: int
    ambiguous_wall: bool
    nonexistent_wall: bool
    payload_open_matches: bool
    payload_available_matches: bool


def wall_to_utc(wall: datetime, tz: ZoneInfo) -> datetime:
    """زمان دیواری سرور را با قواعد DST به UTC واقعی تبدیل می‌کند."""
    return wall.replace(tzinfo=tz).astimezone(UTC)


def wall_dst_flags(wall: datetime, tz: ZoneInfo) -> tuple[bool, bool]:
    first = wall.replace(tzinfo=tz, fold=0)
    second = wall.replace(tzinfo=tz, fold=1)
    roundtrip = first.astimezone(UTC).astimezone(tz).replace(tzinfo=None)
    nonexistent = roundtrip != wall
    ambiguous = not nonexistent and first.utcoffset() != second.utcoffset()
    return ambiguous, nonexistent


def _convert_column(value: str, tz: ZoneInfo) -> dict[str, Any]:
    wall = parse_ts(value).replace(tzinfo=None)
    new = wall_to_utc(wall, tz)
    ambiguous, nonexistent = wall_dst_flags(wall, tz)
    return {
        "new": format_ts(new),
        "shift_seconds": int((new - parse_ts(value)).total_seconds()),
        "ambiguous": ambiguous,
        "nonexistent": nonexistent,
    }


def _convert_raw_row(raw: tuple, tz: ZoneInfo) -> PlannedRow:
    instrument, timeframe, open_time, revision, available_at, payload_text = raw
    open_conv = _convert_column(open_time, tz)
    available_conv = _convert_column(available_at, tz)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        payload = {}
    return PlannedRow(
        instrument_id=instrument,
        timeframe=timeframe,
        revision=int(revision),
        old_open=open_time,
        new_open=open_conv["new"],
        old_available=available_at,
        new_available=available_conv["new"],
        shift_seconds=open_conv["shift_seconds"],
        ambiguous_wall=bool(open_conv["ambiguous"] or available_conv["ambiguous"]),
        nonexistent_wall=bool(open_conv["nonexistent"] or available_conv["nonexistent"]),
        payload_open_matches=payload.get("bar_open_time_utc") == open_time,
        payload_available_matches=payload.get("available_at") == available_at,
    )


def build_plan(
    conn: sqlite3.Connection,
    *,
    broker_timezone: str = "Europe/Athens",
    rebuild_timeframes: tuple[str, ...] = ("M15",),
    now: datetime | None = None,
) -> dict[str, Any]:
    tz = ZoneInfo(broker_timezone)
    checked_at = now or datetime.now(tz=UTC)
    rebuild_set = {tf.upper() for tf in rebuild_timeframes}
    query = (
        "select instrument_id, timeframe, open_time, revision, available_at, payload "
        "from candles where source_id = ? "
        "order by instrument_id, timeframe, open_time, revision"
    )
    raw_rows = conn.execute(query, (SOURCE_ID,)).fetchall()

    planned: list[PlannedRow] = []
    rebuild: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"rows": 0, "groups": set(), "revisions": Counter(), "old_min": None, "old_max": None}
    )
    problems: dict[str, list[dict[str, Any]]] = {
        "non_injective_groups": [],
        "ambiguous_walls": [],
        "nonexistent_walls": [],
        "payload_mismatches": [],
        "future_rows": [],
        "invalid_order": [],
        "duplicate_new_keys": [],
    }
    new_keys: Counter[tuple[str, str, str, int]] = Counter()
    per_group: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"rows": 0, "shifts": Counter(), "old_min": None, "old_max": None,
                 "new_min": None, "new_max": None, "ambiguous": 0, "nonexistent": 0,
                 "revisions": Counter(), "old_times": set(), "new_times": set()}
    )

    for raw in raw_rows:
        instrument, timeframe, open_time, revision, available_at, _payload = raw
        if timeframe in rebuild_set:
            info = rebuild[(instrument, timeframe)]
            info["rows"] += 1
            info["groups"].add(open_time)
            info["revisions"][int(revision)] += 1
            info["old_min"] = open_time if info["old_min"] is None else min(info["old_min"], open_time)
            info["old_max"] = open_time if info["old_max"] is None else max(info["old_max"], open_time)
            continue

        row = _convert_raw_row(raw, tz)
        planned.append(row)

        group = per_group[(instrument, timeframe)]
        group["rows"] += 1
        group["shifts"][row.shift_seconds // 3600] += 1
        group["revisions"][int(revision)] += 1
        group["old_min"] = open_time if group["old_min"] is None else min(group["old_min"], open_time)
        group["old_max"] = open_time if group["old_max"] is None else max(group["old_max"], open_time)
        group["new_min"] = row.new_open if group["new_min"] is None else min(group["new_min"], row.new_open)
        group["new_max"] = row.new_open if group["new_max"] is None else max(group["new_max"], row.new_open)
        group["ambiguous"] += int(row.ambiguous_wall)
        group["nonexistent"] += int(row.nonexistent_wall)
        group["old_times"].add(open_time)
        group["new_times"].add(row.new_open)

        new_key = (instrument, timeframe, row.new_open, int(revision))
        new_keys[new_key] += 1
        if row.ambiguous_wall:
            problems["ambiguous_walls"].append({"key": [instrument, timeframe, open_time, int(revision)]})
        if row.nonexistent_wall:
            problems["nonexistent_walls"].append({"key": [instrument, timeframe, open_time, int(revision)]})
        if not (row.payload_open_matches and row.payload_available_matches):
            payload = json.loads(_payload) if _payload else {}
            problems["payload_mismatches"].append({
                "key": [instrument, timeframe, open_time, int(revision)],
                "payload_open": payload.get("bar_open_time_utc"),
                "payload_available": payload.get("available_at"),
            })
        if parse_ts(row.new_open) > checked_at:
            problems["future_rows"].append({"new_open": row.new_open, "key": [instrument, timeframe, open_time, int(revision)]})
        if parse_ts(row.new_available) <= parse_ts(row.new_open):
            problems["invalid_order"].append({
                "new_open": row.new_open, "new_available": row.new_available,
                "key": [instrument, timeframe, open_time, int(revision)],
            })

    for key, count in new_keys.items():
        if count > 1:
            problems["duplicate_new_keys"].append({"key": list(key), "count": count})

    for (instrument, timeframe), group in sorted(per_group.items()):
        if len(group["old_times"]) != len(group["new_times"]):
            problems["non_injective_groups"].append({
                "instrument_id": instrument,
                "timeframe": timeframe,
                "distinct_old_times": len(group["old_times"]),
                "distinct_new_times": len(group["new_times"]),
            })

    shift_histogram: dict[str, Counter] = defaultdict(Counter)
    by_group: list[dict[str, Any]] = []
    for (instrument, timeframe), group in sorted(per_group.items()):
        hours = {str(hours): count for hours, count in sorted(group["shifts"].items())}
        shift_histogram[timeframe].update(group["shifts"])
        by_group.append({
            "instrument_id": instrument,
            "timeframe": timeframe,
            "rows": group["rows"],
            "revisions": {str(rev): count for rev, count in sorted(group["revisions"].items())},
            "shift_hours": hours,
            "old_range": [group["old_min"], group["old_max"]],
            "new_range": [group["new_min"], group["new_max"]],
            "ambiguous_walls": group["ambiguous"],
            "nonexistent_walls": group["nonexistent"],
        })

    rebuild_report: list[dict[str, Any]] = []
    for (instrument, timeframe), info in sorted(rebuild.items()):
        rebuild_report.append({
            "instrument_id": instrument,
            "timeframe": timeframe,
            "rows": info["rows"],
            "groups": len(info["groups"]),
            "revisions": {str(rev): count for rev, count in sorted(info["revisions"].items())},
            "old_range": [info["old_min"], info["old_max"]],
        })

    blocking = (
        len(problems["non_injective_groups"])
        + len(problems["payload_mismatches"])
        + len(problems["invalid_order"])
        + len(problems["duplicate_new_keys"])
    )
    samples = planned[:3] + planned[-3:] if len(planned) > 6 else planned
    rebuild_rows = sum(item["rows"] for item in rebuild_report)

    return {
        "generated_at": format_ts(checked_at),
        "mode": "dry-run",
        "source_id": SOURCE_ID,
        "broker_timezone": broker_timezone,
        "rebuild_timeframes": sorted(rebuild_set),
        "summary": {
            "total_rows": len(raw_rows),
            "shift_rows": len(planned),
            "rebuild_rows": rebuild_rows,
            "shift_groups": len(per_group),
            "blocking_problems": blocking,
            "non_injective_groups": len(problems["non_injective_groups"]),
            "ambiguous_walls": len(problems["ambiguous_walls"]),
            "nonexistent_walls": len(problems["nonexistent_walls"]),
            "payload_mismatches": len(problems["payload_mismatches"]),
            "future_rows": len(problems["future_rows"]),
            "invalid_order": len(problems["invalid_order"]),
        },
        "shift_histogram_hours": {
            timeframe: {str(hours): count for hours, count in sorted(counter.items())}
            for timeframe, counter in sorted(shift_histogram.items())
        },
        "by_instrument_timeframe": by_group,
        "rebuild": rebuild_report,
        "problems": problems,
        "samples": [asdict(row) for row in samples],
    }


def write_details(rows: list[PlannedRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")


def _collect_plan_rows(
    conn: sqlite3.Connection,
    *,
    broker_timezone: str,
    rebuild_timeframes: tuple[str, ...] = ("M15",),
) -> list[PlannedRow]:
    tz = ZoneInfo(broker_timezone)
    rebuild_set = {tf.upper() for tf in rebuild_timeframes}
    query = (
        "select instrument_id, timeframe, open_time, revision, available_at, payload "
        "from candles where source_id = ? "
        "order by instrument_id, timeframe, open_time, revision"
    )
    return [
        _convert_raw_row(raw, tz)
        for raw in conn.execute(query, (SOURCE_ID,))
        if raw[1] not in rebuild_set
    ]


def _readonly_uri(path: Path) -> str:
    return f"file:{path.as_posix()}?mode=ro"


def _payload_dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _backup_database(db_path: Path, backup_dir: Path, stage: str) -> dict[str, Any]:
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.stem}_{stage}_{stamp}.db"
    source = sqlite3.connect(_readonly_uri(db_path), uri=True)
    try:
        target = sqlite3.connect(str(backup_path))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    check = sqlite3.connect(_readonly_uri(backup_path), uri=True)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        mt5_rows = check.execute(
            "select count(*) from candles where source_id = ?", (SOURCE_ID,)
        ).fetchone()[0]
    finally:
        check.close()
    if integrity != "ok":
        raise RuntimeError(f"backup integrity check failed: {integrity}")
    return {
        "path": str(backup_path),
        "bytes": backup_path.stat().st_size,
        "integrity": integrity,
        "mt5_rows": int(mt5_rows),
    }


def _build_ingestion(db: Database) -> IngestionService:
    settings = Settings.load()
    calendar = TradingCalendar(
        default_holidays(),
        early_closes=default_early_closes(),
        metal_holidays=default_metal_holidays(),
    )
    return IngestionService(
        db=db,
        candles=CandleRepository(db),
        instruments=InstrumentRepository(db),
        quality_runs=DataQualityRepository(db),
        raw_payloads=RawPayloadRepository(db),
        quality=DataQualityEngine(settings.data_quality, calendar),
        audit=AuditLog(db),
        outbox=Outbox(db),
    )


def _shift_row(db: Database, row: PlannedRow, *, now: datetime) -> None:
    current = db.query_one(
        "select revision, is_closed, quality_status, ingested_at, available_at, payload "
        "from candles where instrument_id=? and source_id=? and timeframe=? and open_time=? and revision=?",
        (row.instrument_id, SOURCE_ID, row.timeframe, row.old_open, row.revision),
    )
    if current is None:
        raise RuntimeError(f"row vanished during apply: {row.instrument_id}/{row.timeframe}/{row.old_open}")
    payload = json.loads(current["payload"])
    if payload.get("bar_open_time_utc") != row.old_open or payload.get("available_at") != row.old_available:
        raise RuntimeError(f"payload no longer matches plan: {row.instrument_id}/{row.timeframe}/{row.old_open}")
    if row.new_open != row.old_open and db.query_one(
        "select 1 from candles where instrument_id=? and source_id=? and timeframe=? and open_time=? and revision=?",
        (row.instrument_id, SOURCE_ID, row.timeframe, row.new_open, row.revision),
    ):
        raise RuntimeError(f"target key already exists: {row.instrument_id}/{row.timeframe}/{row.new_open}")

    delta = Timeframe.parse(row.timeframe).delta
    close_time = format_ts(parse_ts(row.new_open) + delta)
    old_digest = Candle.from_dict(payload).digest()
    payload.update({
        "bar_open_time_utc": row.new_open,
        "available_at": row.new_available,
        "close_time_utc": close_time,
    })
    new_digest = Candle.from_dict(payload).digest()

    db.execute(
        "delete from candles where instrument_id=? and source_id=? and timeframe=? and open_time=? and revision=?",
        (row.instrument_id, SOURCE_ID, row.timeframe, row.old_open, row.revision),
    )
    db.execute(
        "insert into candles (instrument_id, source_id, timeframe, open_time, revision, is_closed, quality_status, "
        "available_at, ingested_at, payload) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row.instrument_id, SOURCE_ID, row.timeframe, row.new_open, row.revision, int(current["is_closed"]),
         current["quality_status"], row.new_available, current["ingested_at"], _payload_dump(payload)),
    )
    db.execute(
        "insert into candle_revision_log (instrument_id, source_id, timeframe, open_time, old_revision, new_revision, "
        "old_digest, new_digest, reason, created_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row.instrument_id, SOURCE_ID, row.timeframe, row.old_open, row.revision, row.revision,
         old_digest, new_digest, f"timestamp_repair:{row.new_open}", format_ts(now)),
    )


def _verify_shift(db: Database, plan: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    total = int(db.scalar("select count(*) from candles where source_id=?", (SOURCE_ID,)))
    if total != plan["summary"]["total_rows"]:
        issues.append(f"row count changed: {total} != {plan['summary']['total_rows']}")

    logged = int(db.scalar(
        "select count(*) from candle_revision_log where source_id=? and reason like 'timestamp_repair:%'",
        (SOURCE_ID,),
    ))
    if logged != plan["summary"]["shift_rows"]:
        issues.append(f"revision log rows {logged} != shifted rows {plan['summary']['shift_rows']}")

    for group in plan["by_instrument_timeframe"]:
        rows = db.query(
            "select open_time, revision, available_at, payload from candles "
            "where instrument_id=? and source_id=? and timeframe=? order by open_time",
            (group["instrument_id"], SOURCE_ID, group["timeframe"]),
        )
        label = f"{group['instrument_id']}/{group['timeframe']}"
        if len(rows) != group["rows"]:
            issues.append(f"{label}: rows {len(rows)} != planned {group['rows']}")
            continue
        if rows[0]["open_time"] != group["new_range"][0] or rows[-1]["open_time"] != group["new_range"][1]:
            issues.append(f"{label}: range {rows[0]['open_time']}..{rows[-1]['open_time']} != {group['new_range']}")
        delta = Timeframe.parse(group["timeframe"]).delta
        for stored in rows:
            payload = json.loads(stored["payload"])
            expected_close = format_ts(parse_ts(stored["open_time"]) + delta)
            if (
                payload.get("bar_open_time_utc") != stored["open_time"]
                or payload.get("available_at") != stored["available_at"]
                or payload.get("close_time_utc") != expected_close
            ):
                issues.append(f"{label}: payload mismatch at {stored['open_time']}")
                break
    return issues


def apply_shift(
    db_path: Path,
    *,
    broker_timezone: str,
    rebuild_timeframes: tuple[str, ...],
    backup_dir: Path,
    actor: str,
) -> tuple[dict[str, Any], int]:
    conn = sqlite3.connect(_readonly_uri(db_path), uri=True)
    try:
        plan = build_plan(
            conn, broker_timezone=broker_timezone, rebuild_timeframes=rebuild_timeframes,
        )
        rows = _collect_plan_rows(
            conn, broker_timezone=broker_timezone, rebuild_timeframes=rebuild_timeframes,
        )
    finally:
        conn.close()
    if plan["summary"]["blocking_problems"]:
        return {
            "mode": "apply-shift",
            "status": "refused",
            "reason": "plan has blocking problems",
            "summary": plan["summary"],
            "problems": plan["problems"],
        }, 1

    backup = _backup_database(db_path, backup_dir, "shift")
    db = Database(db_path)
    now = datetime.now(tz=UTC)
    try:
        with db.transaction():
            for row in rows:
                _shift_row(db, row, now=now)
            entry = AuditLog(db).append(
                AuditAction.DATA_TIMESTAMP_REPAIRED, "candle_batch", f"mt5:shift:{format_ts(now)}",
                actor=actor,
                payload={
                    "source_id": SOURCE_ID,
                    "broker_timezone": broker_timezone,
                    "shifted_rows": len(rows),
                    "groups": plan["summary"]["shift_groups"],
                    "revisions": plan["shift_histogram_hours"],
                    "backup": backup["path"],
                },
            )
            audit_state = AuditLog(db).verify()
        verification = _verify_shift(db, plan)
    finally:
        db.close()

    report = {
        "mode": "apply-shift",
        "status": "applied" if not verification else "applied-with-issues",
        "generated_at": format_ts(now),
        "backup": backup,
        "summary": plan["summary"],
        "audit_event_id": entry.event_id,
        "audit_chain": audit_state,
        "verification_issues": verification,
        "by_instrument_timeframe": plan["by_instrument_timeframe"],
    }
    return report, 0 if not verification else 3


def _groups_for_rebuild(conn: sqlite3.Connection, timeframes: tuple[str, ...]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in timeframes)
    rows = conn.execute(
        "select instrument_id, timeframe, count(*) as rows, count(distinct open_time) as groups_, "
        "min(open_time) as old_min, max(open_time) as old_max, max(revision) as max_revision "
        f"from candles where source_id = ? and timeframe in ({placeholders}) "
        "group by instrument_id, timeframe order by instrument_id, timeframe",
        (SOURCE_ID, *timeframes),
    ).fetchall()
    return [
        {
            "instrument_id": row[0], "timeframe": row[1], "rows": int(row[2]),
            "groups": int(row[3]), "old_min": row[4], "old_max": row[5],
            "max_revision": int(row[6]),
        }
        for row in rows
    ]


def _fetch_rebuild_candles(
    groups: list[dict[str, Any]], *, now: datetime,
) -> dict[tuple[str, str], list[Candle]]:
    import MetaTrader5 as mt5

    if not mt5.initialize():
        code, message = mt5.last_error()
        raise RuntimeError(f"MT5 initialize failed: ({code}) {message}")
    fetched: dict[tuple[str, str], list[Candle]] = {}
    try:
        for group in groups:
            start = parse_ts(group["old_min"]) - timedelta(days=2)
            candles = download_from_mt5(
                symbol=group["instrument_id"], timeframe=group["timeframe"],
                start=start, end=now, mt5=mt5,
            )
            candles = sorted((c for c in candles if c.available_at <= now), key=lambda c: c.open_time)
            label = f"{group['instrument_id']}/{group['timeframe']}"
            if not candles:
                raise RuntimeError(f"{label}: no live candles returned")
            if candles[0].open_time > parse_ts(group["old_min"]):
                raise RuntimeError(
                    f"{label}: live history starts {candles[0].open_time.isoformat()} "
                    f"after stored start {group['old_min']}"
                )
            if candles[-1].open_time < parse_ts(group["old_max"]):
                raise RuntimeError(
                    f"{label}: live history ends {candles[-1].open_time.isoformat()} "
                    f"before stored end {group['old_max']}"
                )
            times = [c.open_time for c in candles]
            if len(times) != len(set(times)):
                raise RuntimeError(f"{label}: live history has duplicate open times")
            fetched[(group["instrument_id"], group["timeframe"])] = candles
    finally:
        mt5.shutdown()
    return fetched


def _verify_rebuild(
    db: Database, groups: list[dict[str, Any]], fetched: dict[tuple[str, str], list[Candle]],
) -> list[str]:
    issues: list[str] = []
    for group in groups:
        key = (group["instrument_id"], group["timeframe"])
        label = f"{key[0]}/{key[1]}"
        stored = db.query(
            "select open_time, revision, available_at, payload from candles "
            "where instrument_id=? and source_id=? and timeframe=? order by open_time",
            (key[0], SOURCE_ID, key[1]),
        )
        live = fetched[key]
        if not stored:
            issues.append(f"{label}: no rows after rebuild")
            continue
        if int(max(row["revision"] for row in stored)) != 1:
            issues.append(f"{label}: rebuilt rows are not revision 1")
        stored_times = [row["open_time"] for row in stored]
        live_times = [format_ts(c.open_time) for c in live]
        if stored_times != live_times:
            missing = len(set(live_times) - set(stored_times))
            extra = len(set(stored_times) - set(live_times))
            issues.append(f"{label}: row set differs from live (missing={missing}, extra={extra})")
            continue
        live_by_time = {format_ts(c.open_time): c for c in live}
        for row in stored:
            candle = live_by_time[row["open_time"]]
            if (
                row["available_at"] != format_ts(candle.available_at)
                or json.loads(row["payload"]).get("close") != format(candle.close, "f")
            ):
                issues.append(f"{label}: value mismatch at {row['open_time']}")
                break
    return issues


def apply_rebuild(
    db_path: Path,
    *,
    timeframes: tuple[str, ...],
    backup_dir: Path,
    actor: str,
) -> tuple[dict[str, Any], int]:
    now = datetime.now(tz=UTC)
    conn = sqlite3.connect(_readonly_uri(db_path), uri=True)
    try:
        groups = _groups_for_rebuild(conn, timeframes)
    finally:
        conn.close()
    if not groups:
        return {"mode": "apply-rebuild", "status": "refused", "reason": "no rows to rebuild"}, 1

    try:
        fetched = _fetch_rebuild_candles(groups, now=now)
    except RuntimeError as exc:
        return {"mode": "apply-rebuild", "status": "refused", "reason": str(exc)}, 1

    backup = _backup_database(db_path, backup_dir, "rebuild")
    db = Database(db_path)
    try:
        ingestion = _build_ingestion(db)
        deleted: dict[str, int] = {}
        results: dict[str, dict[str, Any]] = {}
        with db.transaction():
            for group in groups:
                key = (group["instrument_id"], group["timeframe"])
                cursor = db.execute(
                    "delete from candles where instrument_id=? and source_id=? and timeframe=?",
                    (key[0], SOURCE_ID, key[1]),
                )
                deleted[f"{key[0]}/{key[1]}"] = int(cursor.rowcount)
            for group in groups:
                key = (group["instrument_id"], group["timeframe"])
                series = fetched[key]
                result = ingestion.ingest(
                    series, instrument_id=key[0], source_id=SOURCE_ID,
                    now=max(candle.available_at for candle in series),
                )
                results[f"{key[0]}/{key[1]}"] = {
                    "accepted": result.accepted,
                    "quarantined": result.quarantined,
                    "duplicates": result.duplicates,
                    "revised": result.revised,
                    "quality_verdict": result.quality.verdict if result.quality else None,
                }
            entry = AuditLog(db).append(
                AuditAction.DATA_TIMESTAMP_REBUILT, "candle_batch", f"mt5:rebuild:{format_ts(now)}",
                actor=actor,
                payload={
                    "source_id": SOURCE_ID,
                    "timeframes": list(timeframes),
                    "deleted_rows": deleted,
                    "ingested_rows": {k: v["accepted"] for k, v in results.items()},
                    "backup": backup["path"],
                },
            )
            audit_state = AuditLog(db).verify()
        verification = _verify_rebuild(db, groups, fetched)
    finally:
        db.close()

    report = {
        "mode": "apply-rebuild",
        "status": "applied" if not verification else "applied-with-issues",
        "generated_at": format_ts(now),
        "backup": backup,
        "deleted": deleted,
        "ingested": results,
        "audit_event_id": entry.event_id,
        "audit_chain": audit_state,
        "verification_issues": verification,
    }
    return report, 0 if not verification else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "data" / "fxars.db"))
    parser.add_argument("--broker-timezone", default="Europe/Athens")
    parser.add_argument(
        "--rebuild-timeframes", nargs="+", default=["M15"],
        help="timeframes whose rows are rebuilt from live MT5 instead of shifted (default: M15)",
    )
    parser.add_argument("--report", default=str(ROOT / "data" / "tmp_tests" / "mt5_time_repair_dryrun.json"))
    parser.add_argument("--details", default=None)
    parser.add_argument("--apply", action="store_true", help="apply the timestamp shift (writes DB)")
    parser.add_argument("--apply-rebuild", action="store_true", help="rebuild mixed timeframes from live MT5 (writes DB)")
    parser.add_argument("--backup-dir", default=None, help="default: <db dir>/backups")
    parser.add_argument("--actor", default="repair-script")
    parser.add_argument("--apply-report", default=None)
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 2

    rebuild_timeframes = tuple(tf.upper() for tf in args.rebuild_timeframes)
    conn = sqlite3.connect(_readonly_uri(db_path), uri=True)
    try:
        report = build_plan(
            conn, broker_timezone=args.broker_timezone, rebuild_timeframes=rebuild_timeframes,
        )
        rows = _collect_plan_rows(
            conn, broker_timezone=args.broker_timezone, rebuild_timeframes=rebuild_timeframes,
        )
    finally:
        conn.close()

    report["db"] = str(db_path)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.details:
        write_details(rows, Path(args.details))

    summary = report["summary"]
    print("dry-run:", report_path)
    print(
        "total={total_rows} shift_rows={shift_rows} rebuild_rows={rebuild_rows} "
        "groups={shift_groups} blocking={blocking_problems} "
        "ambiguous={ambiguous_walls} nonexistent={nonexistent_walls} "
        "payload_mismatch={payload_mismatches}".format(**summary)
    )
    for group in report["by_instrument_timeframe"]:
        shifts = ", ".join(f"{hours}h x{count}" for hours, count in group["shift_hours"].items())
        print(
            f"  {group['instrument_id']:7} {group['timeframe']:3} "
            f"rows={group['rows']:5} shifts={shifts} "
            f"{group['old_range'][0]} -> {group['old_range'][1]}"
        )
    if report["rebuild"]:
        print(f"rebuild from live MT5 ({', '.join(report['rebuild_timeframes'])}):")
        for group in report["rebuild"]:
            print(
                f"  {group['instrument_id']:7} {group['timeframe']:3} "
                f"rows={group['rows']:5} groups={group['groups']:5} "
                f"revisions={group['revisions']} "
                f"{group['old_range'][0]} -> {group['old_range'][1]}"
            )

    if not (args.apply or args.apply_rebuild):
        return 1 if summary["blocking_problems"] else 0

    backup_dir = Path(args.backup_dir) if args.backup_dir else db_path.parent / "backups"
    apply_report_path = (
        Path(args.apply_report) if args.apply_report
        else ROOT / "data" / "tmp_tests" / f"mt5_time_repair_apply_{datetime.now(tz=UTC):%Y%m%dT%H%M%SZ}.json"
    )
    stages: list[dict[str, Any]] = []
    exit_code = 0

    if args.apply:
        stage_report, code = apply_shift(
            db_path, broker_timezone=args.broker_timezone, rebuild_timeframes=rebuild_timeframes,
            backup_dir=backup_dir, actor=args.actor,
        )
        stages.append(stage_report)
        print(f"apply-shift: {stage_report['status']}")
        if stage_report.get("backup"):
            print(f"  backup: {stage_report['backup']['path']} ({stage_report['backup']['bytes']} bytes)")
        if stage_report.get("verification_issues"):
            for issue in stage_report["verification_issues"]:
                print(f"  ISSUE: {issue}")
        exit_code = max(exit_code, code)
        if code != 0:
            combined = {
                "generated_at": format_ts(datetime.now(tz=UTC)),
                "db": str(db_path),
                "stages": stages,
            }
            apply_report_path.parent.mkdir(parents=True, exist_ok=True)
            apply_report_path.write_text(
                json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            return exit_code

    if args.apply_rebuild:
        stage_report, code = apply_rebuild(
            db_path, timeframes=rebuild_timeframes, backup_dir=backup_dir, actor=args.actor,
        )
        stages.append(stage_report)
        print(f"apply-rebuild: {stage_report['status']}")
        if stage_report.get("backup"):
            print(f"  backup: {stage_report['backup']['path']} ({stage_report['backup']['bytes']} bytes)")
        for label, info in stage_report.get("ingested", {}).items():
            print(f"  {label}: accepted={info['accepted']} quarantined={info['quarantined']} "
                  f"verdict={info['quality_verdict']}")
        if stage_report.get("verification_issues"):
            for issue in stage_report["verification_issues"]:
                print(f"  ISSUE: {issue}")
        exit_code = max(exit_code, code)

    combined = {
        "generated_at": format_ts(datetime.now(tz=UTC)),
        "db": str(db_path),
        "stages": stages,
    }
    apply_report_path.parent.mkdir(parents=True, exist_ok=True)
    apply_report_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    print("apply report:", apply_report_path)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
