"""Repositoryهای SQLite با payload JSON.

هر Repository فقط I/O است؛ قواعد دامنه در سرویس‌ها اعمال می‌شوند.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from typing import Any

from fxars.core.errors import NotFoundError
from fxars.core.ids import stable_id
from fxars.core.numerics import to_decimal
from fxars.core.timeutil import format_ts, parse_ts, utcnow
from fxars.domain.enums import (
    AnalysisStatus,
    OrderStatus,
    RiskReasonCode,
    Role,
    ScenarioStatus,
    Side,
    Timeframe,
)
from fxars.domain.models import (
    AccountSnapshot,
    AnalysisRun,
    AuditEntry,
    BacktestRun,
    BrokerOrder,
    Candle,
    DataQualityRun,
    DataSource,
    EconomicEvent,
    Evidence,
    Fill,
    Instrument,
    ModelRecord,
    OrderIntent,
    Position,
    RiskCheck,
    RiskDecision,
    Scenario,
    ScenarioTransition,
    SessionRecord,
    User,
)
from fxars.storage.db import Database


def _dump(obj: Any) -> str:
    from fxars.core.serde import jsonable

    return json.dumps(jsonable(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(text: str) -> dict[str, Any]:
    return json.loads(text)


def _row_payload(row: Any) -> dict[str, Any]:
    return _load(row["payload"])


class InstrumentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, instrument: Instrument) -> None:
        self.db.execute(
            "INSERT INTO instruments (instrument_id, version, payload, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(instrument_id) DO UPDATE SET version=excluded.version, payload=excluded.payload, updated_at=excluded.updated_at",
            (instrument.instrument_id, instrument.version, _dump(instrument), format_ts(utcnow())),
        )

    def get(self, instrument_id: str) -> Instrument:
        row = self.db.query_one("SELECT payload FROM instruments WHERE instrument_id = ?", (instrument_id,))
        if row is None:
            raise NotFoundError(f"نماد {instrument_id} در سامانه ثبت نشده است.", details={"instrument_id": instrument_id})
        return Instrument.from_dict(_row_payload(row))

    def find(self, instrument_id: str) -> Instrument | None:
        row = self.db.query_one("SELECT payload FROM instruments WHERE instrument_id = ?", (instrument_id,))
        return Instrument.from_dict(_row_payload(row)) if row else None

    def list(self) -> list[Instrument]:
        rows = self.db.query("SELECT payload FROM instruments ORDER BY instrument_id")
        return [Instrument.from_dict(_row_payload(row)) for row in rows]

    def save_source(self, source: DataSource) -> None:
        self.db.execute(
            "INSERT INTO data_sources (source_id, payload, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(source_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (source.source_id, _dump(source), format_ts(utcnow())),
        )

    def get_source(self, source_id: str) -> DataSource | None:
        row = self.db.query_one("SELECT payload FROM data_sources WHERE source_id = ?", (source_id,))
        if row is None:
            return None
        return DataSource(**_row_payload(row))

    def list_sources(self) -> list[DataSource]:
        # FIX-SOURCES-ORDER: priority در payload است، نه ستون
        rows = list(self.db.query("SELECT payload FROM data_sources"))
        sources = [DataSource(**_row_payload(row)) for row in rows]
        sources.sort(key=lambda s: s.priority)
        return sources

    def map_symbol(self, source_id: str, broker_symbol: str, instrument_id: str,
                   valid_from: datetime, valid_to: datetime | None = None) -> None:
        payload = {
            "source_id": source_id,
            "broker_symbol": broker_symbol,
            "instrument_id": instrument_id,
            "valid_from": format_ts(valid_from),
            "valid_to": format_ts(valid_to) if valid_to else None,
        }
        self.db.execute(
            "INSERT OR REPLACE INTO symbol_mappings (source_id, broker_symbol, instrument_id, valid_from, valid_to, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (source_id, broker_symbol, instrument_id, format_ts(valid_from), payload["valid_to"], _dump(payload)),
        )

    def resolve_symbol(self, source_id: str, broker_symbol: str, at: datetime) -> str | None:
        row = self.db.query_one(
            "SELECT instrument_id FROM symbol_mappings WHERE source_id=? AND broker_symbol=? "
            "AND valid_from<=? AND (valid_to IS NULL OR valid_to>=?) ORDER BY valid_from DESC LIMIT 1",
            (source_id, broker_symbol, format_ts(at), format_ts(at)),
        )
        return row["instrument_id"] if row else None

    def primary_source(self, instrument_id: str, timeframe: str) -> str:
        """FIX-03-PRIMARY-SOURCE: انتخاب منبع اصلی برای تحلیل/بک‌تست.

        اگر فقط یک منبع وجود دارد همان برگردانده می‌شود؛ در غیر این صورت از
        DataSource.priority استفاده می‌شود؛ در نهایت نام منبع به‌صورت صریح خطا می‌دهد.
        """
        sources = self.db.query(
            "SELECT source_id FROM candles WHERE instrument_id=? AND timeframe=? "
            "GROUP BY source_id ORDER BY source_id",
            (instrument_id, Timeframe.parse(timeframe).value),
        )
        ids = [row["source_id"] for row in sources]
        if not ids:
            raise NotFoundError(
                f"هیچ منبع داده‌ای برای {instrument_id}/{timeframe} ثبت نشده است.",
                details={"instrument_id": instrument_id, "timeframe": timeframe},
            )
        if len(ids) == 1:
            return ids[0]
        priority_rows = self.db.query(
            "SELECT source_id, payload FROM data_sources WHERE source_id IN ({})".format(
                ",".join("?" for _ in ids)
            ),
            ids,
        )
        ranked: list[tuple[int, str]] = []
        for row in priority_rows:
            payload = _load(row["payload"])
            ranked.append((int(payload.get("priority", 100)), row["source_id"]))
        ranked.sort()
        for _, sid in ranked:
            if sid in ids:
                return sid
        return ids[0]

    def seed_defaults(self, instruments: Iterable[Instrument], source: DataSource) -> int:
        count = 0
        for instrument in instruments:
            self.save(instrument)
            count += 1
        self.save_source(source)
        return count


class CandleRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(self, candle: Candle) -> tuple[str, int]:
        row = self.db.query_one(
            "SELECT revision, payload FROM candles WHERE instrument_id=? AND source_id=? AND timeframe=? AND open_time=? "
            "ORDER BY revision DESC LIMIT 1",
            (candle.instrument_id, candle.source_id, candle.timeframe, format_ts(candle.open_time)),
        )
        if row is None:
            self._insert(candle, 1)
            return ("inserted", 1)
        existing = Candle.from_dict(_load(row["payload"]))
        if existing.digest() == candle.digest():
            return ("duplicate", int(row["revision"]))
        new_revision = int(row["revision"]) + 1
        stored = Candle.from_dict({**candle.to_dict(), "revision": new_revision})
        self._insert(stored, new_revision)
        self.db.execute(
            "INSERT INTO candle_revision_log (instrument_id, source_id, timeframe, open_time, old_revision, new_revision, "
            "old_digest, new_digest, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (candle.instrument_id, candle.source_id, candle.timeframe, format_ts(candle.open_time),
             int(row["revision"]), new_revision, existing.digest(), candle.digest(), "source_revision", format_ts(utcnow())),
        )
        return ("revised", new_revision)

    def _insert(self, candle: Candle, revision: int) -> None:
        payload = candle.to_dict()
        payload["revision"] = revision
        self.db.execute(
            "INSERT INTO candles (instrument_id, source_id, timeframe, open_time, revision, is_closed, quality_status, "
            "available_at, ingested_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (candle.instrument_id, candle.source_id, candle.timeframe, format_ts(candle.open_time), revision,
             1 if candle.is_closed else 0, candle.quality_status.value, format_ts(candle.available_at),
             format_ts(candle.ingested_at), _dump(payload)),
        )

    def bulk_upsert(self, candles: Iterable[Candle]) -> dict[str, int]:
        stats = {"inserted": 0, "duplicate": 0, "revised": 0}
        with self.db.transaction():
            for candle in candles:
                status, _ = self.upsert(candle)
                stats[status] += 1
        return stats

    def quarantine(self, candle: Candle, reasons: Sequence[str]) -> None:
        self.db.execute(
            "INSERT INTO candle_quarantine (instrument_id, source_id, timeframe, open_time, reasons, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (candle.instrument_id, candle.source_id, candle.timeframe, format_ts(candle.open_time),
             json.dumps(list(reasons), ensure_ascii=False), _dump(candle.to_dict()), format_ts(utcnow())),
        )

    def _base_query(self) -> str:
        return (
            "SELECT c.payload FROM candles c WHERE c.instrument_id=? AND c.timeframe=? "
            "AND c.revision = (SELECT MAX(c2.revision) FROM candles c2 WHERE c2.instrument_id=c.instrument_id "
            "AND c2.source_id=c.source_id AND c2.timeframe=c.timeframe AND c2.open_time=c.open_time)"
        )

    def range(
        self,
        instrument_id: str,
        timeframe: str | Timeframe,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        source_id: str | None = None,
        closed_only: bool = True,
        as_of: datetime | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        tf = Timeframe.parse(timeframe).value
        sql = self._base_query()
        params: list[Any] = [instrument_id, tf]
        if source_id:
            sql += " AND c.source_id=?"
            params.append(source_id)
        if start is not None:
            sql += " AND c.open_time>=?"
            params.append(format_ts(start))
        if end is not None:
            sql += " AND c.open_time<=?"
            params.append(format_ts(end))
        if closed_only:
            sql += " AND c.is_closed=1"
        if as_of is not None:
            sql += " AND c.available_at<=?"
            params.append(format_ts(as_of))
        sql += " ORDER BY c.open_time ASC"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [Candle.from_dict(_row_payload(row)) for row in self.db.query(sql, params)]

    def latest(self, instrument_id: str, timeframe: str | Timeframe, *, source_id: str | None = None) -> Candle | None:
        candles = self.range(instrument_id, timeframe, source_id=source_id, closed_only=True)
        return candles[-1] if candles else None

    def count(self, instrument_id: str, timeframe: str | Timeframe) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM candles WHERE instrument_id=? AND timeframe=?",
                                  (instrument_id, Timeframe.parse(timeframe).value)) or 0)

    def sources(self, instrument_id: str, timeframe: str | Timeframe) -> list[str]:
        rows = self.db.query("SELECT DISTINCT source_id FROM candles WHERE instrument_id=? AND timeframe=? ORDER BY source_id",
                             (instrument_id, Timeframe.parse(timeframe).value))
        return [row["source_id"] for row in rows]

    def latest_available(self, instrument_id: str, timeframe: str | Timeframe, source_id: str | None = None) -> Candle | None:
        return self.latest(instrument_id, timeframe, source_id=source_id)

    def revisions(self, instrument_id: str, timeframe: str | Timeframe) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM candle_revision_log WHERE instrument_id=? AND timeframe=?",
                                  (instrument_id, Timeframe.parse(timeframe).value)) or 0)


class EconomicEventRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, event: EconomicEvent) -> int:
        row = self.db.query_one(
            "SELECT revision, payload FROM economic_events WHERE event_id=? ORDER BY revision DESC LIMIT 1",
            (event.event_id,),
        )
        if row is None:
            revision = 1
        else:
            existing = EconomicEvent(**_load(row["payload"]))
            if _dump(existing) == _dump(event):
                return int(row["revision"])
            revision = int(row["revision"]) + 1
        self.db.execute(
            "INSERT INTO economic_events (event_id, revision, currency, event_time, available_at, importance, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event.event_id, revision, event.currency, format_ts(event.event_time), format_ts(event.available_at),
             event.importance.value, _dump(event)),
        )
        return revision

    def between(self, start: datetime, end: datetime, *, currency: str | None = None,
                as_of: datetime | None = None) -> list[EconomicEvent]:
        sql = (
            "SELECT e.payload FROM economic_events e WHERE e.revision=(SELECT MAX(e2.revision) FROM economic_events e2 "
            "WHERE e2.event_id=e.event_id) AND e.event_time>=? AND e.event_time<=?"
        )
        params: list[Any] = [format_ts(start), format_ts(end)]
        if currency:
            sql += " AND e.currency=?"
            params.append(currency)
        if as_of is not None:
            sql += " AND e.available_at<=?"
            params.append(format_ts(as_of))
        sql += " ORDER BY e.event_time"
        return [EconomicEvent.from_dict(_row_payload(row)) for row in self.db.query(sql, params)]

    def all_latest(self) -> list[EconomicEvent]:
        rows = self.db.query(
            "SELECT payload FROM economic_events e WHERE revision=(SELECT MAX(revision) FROM economic_events e2 "
            "WHERE e2.event_id=e.event_id) ORDER BY event_time"
        )
        return [EconomicEvent.from_dict(_row_payload(row)) for row in rows]


class AnalysisRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save_run(self, run: AnalysisRun) -> None:
        self.db.execute(
            "INSERT INTO analysis_runs (run_id, instrument_id, timeframe, as_of, data_snapshot_id, config_hash, code_version, "
            "model_version, status, correlation_id, started_at, finished_at, result_hash, evidence_count, decision, data_quality, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(run_id) DO NOTHING",
            (run.run_id, run.instrument_id, run.timeframe, format_ts(run.as_of), run.data_snapshot_id, run.config_hash,
             run.code_version, run.model_version, run.status.value, run.correlation_id, format_ts(run.started_at),
             format_ts(run.finished_at) if run.finished_at else None, run.result_hash, run.evidence_count,
             _dump(run.decision), _dump(run.data_quality), run.error),
        )

    def get_run(self, run_id: str) -> AnalysisRun:
        row = self.db.query_one("SELECT * FROM analysis_runs WHERE run_id=?", (run_id,))
        if row is None:
            raise NotFoundError(f"اجرای تحلیل {run_id} یافت نشد.", details={"run_id": run_id})
        return self._decode(row)

    def find_run(self, run_id: str) -> AnalysisRun | None:
        row = self.db.query_one("SELECT * FROM analysis_runs WHERE run_id=?", (run_id,))
        return self._decode(row) if row else None

    @staticmethod
    def _decode(row: Any) -> AnalysisRun:
        return AnalysisRun(
            run_id=row["run_id"],
            instrument_id=row["instrument_id"],
            timeframe=row["timeframe"],
            as_of=parse_ts(row["as_of"]),
            data_snapshot_id=row["data_snapshot_id"],
            config_hash=row["config_hash"],
            code_version=row["code_version"],
            model_version=row["model_version"],
            status=AnalysisStatus(row["status"]),
            correlation_id=row["correlation_id"],
            started_at=parse_ts(row["started_at"]),
            finished_at=parse_ts(row["finished_at"]) if row["finished_at"] else None,
            result_hash=row["result_hash"],
            evidence_count=int(row["evidence_count"]),
            decision=_load(row["decision"]),
            data_quality=_load(row["data_quality"]),
            error=row["error"],
        )

    def list_runs(self, *, instrument_id: str | None = None, limit: int = 50, offset: int = 0) -> list[AnalysisRun]:
        sql = "SELECT run_id FROM analysis_runs"
        params: list[Any] = []
        if instrument_id:
            sql += " WHERE instrument_id=?"
            params.append(instrument_id)
        sql += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [self.get_run(row["run_id"]) for row in self.db.query(sql, params)]

    def add_evidence(self, evidences: Iterable[Evidence]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO evidences (evidence_id, run_id, module_id, family, observed_at, available_at, direction, strength, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (item.evidence_id, item.analysis_run_id, item.module_id, item.family.value, format_ts(item.observed_at),
                 format_ts(item.available_at), item.direction.value, float(item.strength), _dump(item))
                for item in evidences
            ],
        )

    def evidence_for(self, run_id: str) -> list[Evidence]:
        # FIX-P1-1b: stable ordering by evidence_id so replay and first run agree.
        rows = self.db.query(
            "SELECT payload FROM evidences WHERE run_id=? ORDER BY evidence_id", (run_id,),
        )
        return [Evidence.from_dict(_row_payload(row)) for row in rows]


class ScenarioRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, scenario: Scenario) -> None:
        self.db.execute(
            "INSERT INTO scenarios (scenario_id, instrument_id, timeframe, direction, status, expiry_at, created_at, updated_at, "
            "risk_decision_id, analysis_run_id, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(scenario_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at, "
            "risk_decision_id=excluded.risk_decision_id, payload=excluded.payload",
            (scenario.scenario_id, scenario.instrument_id, scenario.timeframe, scenario.direction.value,
             scenario.status.value, format_ts(scenario.expiry_at), format_ts(scenario.created_at),
             format_ts(scenario.updated_at), scenario.risk_decision_id, scenario.analysis_run_id, _dump(scenario)),
        )

    def get(self, scenario_id: str) -> Scenario:
        row = self.db.query_one("SELECT payload FROM scenarios WHERE scenario_id=?", (scenario_id,))
        if row is None:
            raise NotFoundError(f"سناریو {scenario_id} یافت نشد.", details={"scenario_id": scenario_id})
        return Scenario.from_dict(_row_payload(row))

    def list(self, *, status: ScenarioStatus | None = None, instrument_id: str | None = None,
             limit: int = 100, offset: int = 0) -> list[Scenario]:
        sql = "SELECT payload FROM scenarios WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status=?"
            params.append(status.value if isinstance(status, ScenarioStatus) else status)
        if instrument_id:
            sql += " AND instrument_id=?"
            params.append(instrument_id)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [Scenario.from_dict(_row_payload(row)) for row in self.db.query(sql, params)]

    def live(self) -> list[Scenario]:
        rows = self.db.query("SELECT payload FROM scenarios WHERE status IN ('DRAFT','WATCH','ARMED','TRIGGERED') ORDER BY created_at")
        return [Scenario.from_dict(_row_payload(row)) for row in rows]

    def find_by_run(self, run_id: str) -> Scenario | None:
        row = self.db.query_one("SELECT payload FROM scenarios WHERE analysis_run_id=? ORDER BY created_at DESC LIMIT 1", (run_id,))
        return Scenario.from_dict(_row_payload(row)) if row else None

    def count_by_status(self) -> dict[str, int]:
        rows = self.db.query("SELECT status, COUNT(*) AS n FROM scenarios GROUP BY status")
        return {row["status"]: int(row["n"]) for row in rows}

    def add_transition(self, transition: ScenarioTransition) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO scenario_transitions (transition_id, scenario_id, from_status, to_status, event, actor, reason, "
            "occurred_at, rules_version, data_ref, correlation_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (transition.transition_id, transition.scenario_id, transition.from_status.value, transition.to_status.value,
             transition.event, transition.actor, transition.reason, format_ts(transition.occurred_at),
             transition.rules_version, transition.data_ref, transition.correlation_id),
        )

    def transitions(self, scenario_id: str) -> list[ScenarioTransition]:
        rows = self.db.query("SELECT * FROM scenario_transitions WHERE scenario_id=? ORDER BY occurred_at, rowid", (scenario_id,))
        return [
            ScenarioTransition(
                transition_id=row["transition_id"], scenario_id=row["scenario_id"],
                from_status=ScenarioStatus(row["from_status"]), to_status=ScenarioStatus(row["to_status"]),
                event=row["event"], actor=row["actor"], reason=row["reason"],
                occurred_at=parse_ts(row["occurred_at"]), rules_version=row["rules_version"],
                data_ref=row["data_ref"], correlation_id=row["correlation_id"],
            )
            for row in rows
        ]


class RiskRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, decision: RiskDecision) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO risk_decisions (decision_id, scenario_id, instrument_id, approved, reason_code, policy_version, "
            "created_at, valid_until, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (decision.decision_id, decision.scenario_id, decision.instrument_id, 1 if decision.approved else 0,
             decision.reason_code.value, decision.policy_version, format_ts(decision.created_at),
             format_ts(decision.valid_until), _dump(decision)),
        )

    def get(self, decision_id: str) -> RiskDecision:
        row = self.db.query_one("SELECT payload FROM risk_decisions WHERE decision_id=?", (decision_id,))
        if row is None:
            raise NotFoundError(f"تصمیم ریسک {decision_id} یافت نشد.", details={"decision_id": decision_id})
        return self._decode(_row_payload(row))

    def latest_for_scenario(self, scenario_id: str) -> RiskDecision | None:
        row = self.db.query_one("SELECT payload FROM risk_decisions WHERE scenario_id=? ORDER BY created_at DESC LIMIT 1", (scenario_id,))
        return self._decode(_row_payload(row)) if row else None

    def list(self, *, limit: int = 100, offset: int = 0) -> list[RiskDecision]:
        rows = self.db.query("SELECT payload FROM risk_decisions ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
        return [self._decode(_row_payload(row)) for row in rows]

    @staticmethod
    def _decode(data: dict[str, Any]) -> RiskDecision:
        return RiskDecision(
            decision_id=data["decision_id"], scenario_id=data["scenario_id"], instrument_id=data["instrument_id"],
            account_snapshot_id=data["account_snapshot_id"], approved=bool(data["approved"]),
            risk_amount=to_decimal(data["risk_amount"]), risk_currency=data["risk_currency"],
            position_size=to_decimal(data["position_size"]), entry_price=to_decimal(data["entry_price"]),
            stop_loss=to_decimal(data["stop_loss"]),
            take_profit=to_decimal(data["take_profit"]) if data.get("take_profit") else None,
            checks=tuple(RiskCheck(**check) for check in data.get("checks", [])),
            policy_version=data["policy_version"], reason_code=RiskReasonCode(data["reason_code"]),
            reason_detail=data.get("reason_detail", ""), valid_until=parse_ts(data["valid_until"]),
            created_at=parse_ts(data["created_at"]), inputs_hash=data.get("inputs_hash", ""),
            correlation_id=data.get("correlation_id", ""),
        )


class DataQualityRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, run: DataQualityRun) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO data_quality_runs (run_id, instrument_id, timeframe, source_id, checked_at, verdict, stale, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run.run_id, run.instrument_id, run.timeframe, run.source_id, format_ts(run.checked_at), run.verdict,
             1 if run.stale else 0, _dump(run.to_dict())),
        )

    def get(self, run_id: str) -> DataQualityRun | None:
        row = self.db.query_one("SELECT payload FROM data_quality_runs WHERE run_id=?", (run_id,))
        return self._decode(_row_payload(row)) if row else None

    def list(self, *, instrument_id: str | None = None, limit: int = 50) -> list[DataQualityRun]:
        sql = "SELECT payload FROM data_quality_runs"
        params: list[Any] = []
        if instrument_id:
            sql += " WHERE instrument_id=?"
            params.append(instrument_id)
        sql += " ORDER BY checked_at DESC LIMIT ?"
        params.append(limit)
        return [self._decode(_row_payload(row)) for row in self.db.query(sql, params)]

    @staticmethod
    def _decode(data: dict[str, Any]) -> DataQualityRun:
        from fxars.domain.models import DataQualityIssue

        return DataQualityRun(
            run_id=data["run_id"], instrument_id=data["instrument_id"], timeframe=data["timeframe"],
            source_id=data["source_id"], checked_at=parse_ts(data["checked_at"]), total=int(data["total"]),
            valid=int(data["valid"]), suspect=int(data["suspect"]), invalid=int(data["invalid"]),
            missing=int(data["missing"]), stale=bool(data["stale"]), verdict=data["verdict"],
            issues=tuple(DataQualityIssue(**item) for item in data.get("issues", [])),
            latest_bar_age_seconds=float(data.get("latest_bar_age_seconds", 0.0)),
        )


class BacktestRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, run: BacktestRun) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO backtest_runs (run_id, instrument_id, timeframe, segment, config_hash, data_snapshot_id, "
            "started_at, finished_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run.run_id, run.instrument_id, run.timeframe, run.segment.value, run.config_hash, run.data_snapshot_id,
             format_ts(run.started_at), format_ts(run.finished_at), _dump(run.to_dict())),
        )

    def get(self, run_id: str) -> BacktestRun:
        row = self.db.query_one("SELECT payload FROM backtest_runs WHERE run_id=?", (run_id,))
        if row is None:
            raise NotFoundError(f"بک‌تست {run_id} یافت نشد.", details={"run_id": run_id})
        return self._decode(_row_payload(row))

    def list(self, *, limit: int = 50) -> list[BacktestRun]:
        rows = self.db.query("SELECT payload FROM backtest_runs ORDER BY started_at DESC LIMIT ?", (limit,))
        return [self._decode(_row_payload(row)) for row in rows]

    @staticmethod
    def _decode(data: dict[str, Any]) -> BacktestRun:
        from fxars.domain.enums import BacktestSegment

        return BacktestRun(
            run_id=data["run_id"], instrument_id=data["instrument_id"], timeframe=data["timeframe"],
            config=data["config"], config_hash=data["config_hash"], data_snapshot_id=data["data_snapshot_id"],
            code_version=data["code_version"], segment=BacktestSegment(data["segment"]),
            started_at=parse_ts(data["started_at"]), finished_at=parse_ts(data["finished_at"]),
            metrics=data["metrics"], trades=tuple(data["trades"]),
            equity_curve=tuple(tuple(point) for point in data["equity_curve"]), seed=int(data.get("seed", 0)),
        )


class AuditRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(self, entry: AuditEntry) -> None:
        self.db.execute(
            "INSERT INTO audit_events (event_id, occurred_at, actor, action, entity_type, entity_id, correlation_id, payload, "
            "prev_hash, entry_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (entry.event_id, format_ts(entry.occurred_at), entry.actor, entry.action, entry.entity_type, entry.entity_id,
             entry.correlation_id, _dump(entry.payload), entry.prev_hash, entry.entry_hash),
        )

    def last(self) -> AuditEntry | None:
        row = self.db.query_one("SELECT * FROM audit_events ORDER BY seq DESC LIMIT 1")
        return self._decode(row) if row else None

    def list(self, *, limit: int = 100, offset: int = 0, action: str | None = None,
             entity_type: str | None = None) -> list[AuditEntry]:
        sql = "SELECT * FROM audit_events WHERE 1=1"
        params: list[Any] = []
        if action:
            sql += " AND action=?"
            params.append(action)
        if entity_type:
            sql += " AND entity_type=?"
            params.append(entity_type)
        sql += " ORDER BY seq DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [self._decode(row) for row in self.db.query(sql, params)]

    def all(self) -> list[AuditEntry]:
        return [self._decode(row) for row in self.db.query("SELECT * FROM audit_events ORDER BY seq")]

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM audit_events") or 0)

    @staticmethod
    def _decode(row: Any) -> AuditEntry:
        return AuditEntry(
            seq=int(row["seq"]), event_id=row["event_id"], occurred_at=parse_ts(row["occurred_at"]),
            actor=row["actor"], action=row["action"], entity_type=row["entity_type"], entity_id=row["entity_id"],
            correlation_id=row["correlation_id"], payload=_load(row["payload"]), prev_hash=row["prev_hash"],
            entry_hash=row["entry_hash"],
        )


class OutboxRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, event_id: str, event_type: str, schema_version: str, occurred_at: datetime,
            correlation_id: str, payload: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO outbox (event_id, event_type, schema_version, occurred_at, correlation_id, payload, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (event_id, event_type, schema_version, format_ts(occurred_at), correlation_id, _dump(payload)),
        )

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM outbox WHERE published_at IS NULL AND dead_letter_at IS NULL "
            "ORDER BY occurred_at LIMIT ?",
            (limit,),
        )
        return [
            {
                "event_id": row["event_id"], "event_type": row["event_type"],
                "schema_version": row["schema_version"], "occurred_at": row["occurred_at"],
                "correlation_id": row["correlation_id"], "payload": _load(row["payload"]),
                "published_at": row["published_at"], "attempts": int(row["attempts"] or 0),
            }
            for row in rows
        ]

    def attempts_for(self, event_id: str) -> int:
        return int(self.db.scalar("SELECT attempts FROM outbox WHERE event_id=?", (event_id,)) or 0)

    def bump_attempt(self, event_id: str, *, last_error: str = "") -> None:
        self.db.execute(
            "UPDATE outbox SET attempts = attempts + 1, last_error=? WHERE event_id=?",
            (last_error, event_id),
        )

    def mark_dead_letter(self, event_id: str, when, *, reason: str = "") -> None:
        from fxars.core.timeutil import format_ts
        self.db.execute(
            "UPDATE outbox SET dead_letter_at=?, last_error=? WHERE event_id=?",
            (format_ts(when), reason, event_id),
        )

    def dead_letters(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM outbox WHERE dead_letter_at IS NOT NULL ORDER BY dead_letter_at LIMIT ?",
            (limit,),
        )
        return [
            {
                "event_id": row["event_id"], "event_type": row["event_type"],
                "dead_letter_at": row["dead_letter_at"], "last_error": row["last_error"],
                "attempts": int(row["attempts"] or 0),
            }
            for row in rows
        ]

    def mark_published(self, event_id: str, when: datetime) -> None:
        self.db.execute("UPDATE outbox SET published_at=? WHERE event_id=?", (format_ts(when), event_id))

    def is_consumed(self, consumer: str, event_id: str) -> bool:
        return self.db.query_one("SELECT 1 FROM outbox_consumed WHERE consumer=? AND event_id=?", (consumer, event_id)) is not None

    def mark_consumed(self, consumer: str, event_id: str, when: datetime) -> None:
        self.db.execute("INSERT OR IGNORE INTO outbox_consumed (consumer, event_id, consumed_at) VALUES (?, ?, ?)",
                        (consumer, event_id, format_ts(when)))

    def count_pending(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM outbox WHERE published_at IS NULL") or 0)


class SystemStateRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.query_one("SELECT value FROM system_state WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value: Any, actor: str) -> None:
        self.db.execute(
            "INSERT INTO system_state (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (key, json.dumps(value, ensure_ascii=False), format_ts(utcnow()), actor),
        )


class UserRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, user: User) -> None:
        self.db.execute(
            "INSERT INTO users (user_id, username, role, password_hash, totp_secret_enc, active, created_at, tenant_id, display_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, role=excluded.role, "
            "password_hash=excluded.password_hash, totp_secret_enc=excluded.totp_secret_enc, active=excluded.active, "
            "tenant_id=excluded.tenant_id, display_name=excluded.display_name",
            (user.user_id, user.username, user.role.value, user.password_hash, user.totp_secret_enc, 1 if user.active else 0,
             format_ts(user.created_at), user.tenant_id, user.display_name),
        )

    def get_by_username(self, username: str) -> User | None:
        row = self.db.query_one("SELECT * FROM users WHERE username=?", (username,))
        return self._decode(row) if row else None

    def get(self, user_id: str) -> User | None:
        row = self.db.query_one("SELECT * FROM users WHERE user_id=?", (user_id,))
        return self._decode(row) if row else None

    def list(self) -> list[User]:
        return [self._decode(row) for row in self.db.query("SELECT * FROM users ORDER BY username")]

    @staticmethod
    def _decode(row: Any) -> User:
        return User(
            user_id=row["user_id"], username=row["username"], role=Role(row["role"]), password_hash=row["password_hash"],
            totp_secret_enc=row["totp_secret_enc"], active=bool(row["active"]), created_at=parse_ts(row["created_at"]),
            tenant_id=row["tenant_id"], display_name=row["display_name"],
        )


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, session: SessionRecord) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO sessions (token_hash, user_id, created_at, expires_at, ip, revoked) VALUES (?, ?, ?, ?, ?, ?)",
            (session.token_hash, session.user_id, format_ts(session.created_at), format_ts(session.expires_at),
             session.ip, 1 if session.revoked else 0),
        )

    def get(self, token_hash: str) -> SessionRecord | None:
        row = self.db.query_one("SELECT * FROM sessions WHERE token_hash=?", (token_hash,))
        if row is None:
            return None
        return SessionRecord(
            token_hash=row["token_hash"], user_id=row["user_id"], created_at=parse_ts(row["created_at"]),
            expires_at=parse_ts(row["expires_at"]), ip=row["ip"], revoked=bool(row["revoked"]),
        )

    def revoke(self, token_hash: str) -> None:
        self.db.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?", (token_hash,))

    def revoke_all(self, user_id: str) -> int:
        """FIX-P0-3: revoke all active sessions for a user (password/role change)."""
        cur = self.db.execute("UPDATE sessions SET revoked=1 WHERE user_id=? AND revoked=0", (user_id,))
        return cur.rowcount

    def purge_expired(self, now: datetime) -> int:
        cur = self.db.execute("DELETE FROM sessions WHERE expires_at < ?", (format_ts(now),))
        return cur.rowcount


class LoginAttemptRepository:
    """FIX-P1-2: شمارش شکست‌های متوالی ورود با ترتیب ثبت (id) — نه مقایسه رشته‌ای زمان.

    دلیل: وقتی چند شکست در همان ثانیه ثبت می‌شوند، کوئری ``attempted_at > MAX(success)``
    آن‌ها را از دست می‌دهد. با ``ORDER BY id DESC`` ترتیب واقعی ثبت حفظ می‌شود.
    """

    def __init__(self, db: Database, clock: Callable[[], datetime] | None = None) -> None:
        self.db = db
        self._clock = clock

    def _now(self) -> datetime:
        return self._clock() if self._clock is not None else utcnow()

    def add(self, username: str, ip: str, success: bool) -> None:
        self.db.execute(
            "INSERT INTO login_attempts (username, ip, attempted_at, success) VALUES (?, ?, ?, ?)",
            (username, ip, format_ts(self._now()), 1 if success else 0),
        )

    def failures_since(self, username: str, since: datetime) -> int:
        """تعداد شکست‌های متوالی از آخرین ورودِ موفق تا کنون (در پنجره since)."""
        rows = self.db.query(
            "SELECT success FROM login_attempts "
            "WHERE username=? AND attempted_at>=? "
            "ORDER BY id DESC",
            (username, format_ts(since)),
        )
        count = 0
        for row in rows:
            if row["success"]:
                break
            count += 1
        return count


class IdempotencyRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, user_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM idempotency_keys WHERE key=? AND user_id=?", (key, user_id))
        if row is None:
            return None
        return {"route": row["route"], "request_hash": row["request_hash"], "status": int(row["status"]),
                "response": _load(row["response"])}

    def put(self, key: str, user_id: str, route: str, request_hash: str, status: int, response: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO idempotency_keys (key, user_id, route, request_hash, status, response, created_at, state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'completed')",
            (key, user_id, route, request_hash, status, _dump(response), format_ts(utcnow())),
        )

    def begin(self, key: str, user_id: str, route: str, request_hash: str) -> tuple[str, dict[str, Any] | None]:
        """FIX-09-IDEMPOTENCY-ATOMIC: ثبت pending اتمیک قبل از Action.

        ("replay", response)  | ("conflict", None) | ("in_progress", None) | ("proceed", None)
        """
        row = self.db.query_one(
            "SELECT state, request_hash, status, response FROM idempotency_keys WHERE key=? AND user_id=?",
            (key, user_id),
        )
        if row is not None:
            state = row["state"] or "completed"
            # FIX-09-IDEMPOTENCY-ATOMIC: state='failed' → همیشه اجازه retry (حتی با hash متفاوت)
            if state == "failed":
                # fall through → اجرای دوباره با hash جدید
                pass
            elif row["request_hash"] != request_hash:
                # completed/pending با hash متفاوت → conflict
                return ("conflict", None)
            elif state == "completed":
                return ("replay", {"status": int(row["status"]), "response": _load(row["response"])})
            elif state == "pending":
                return ("in_progress", None)
        self.db.execute(
            "INSERT OR REPLACE INTO idempotency_keys "
            "(key, user_id, route, request_hash, status, response, created_at, state) "
            "VALUES (?, ?, ?, ?, 0, '{}', ?, 'pending')",
            (key, user_id, route, request_hash, format_ts(utcnow())),
        )
        return ("proceed", None)

    def complete(self, key: str, user_id: str, status: int, response: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE idempotency_keys SET status=?, response=?, state='completed' "
            "WHERE key=? AND user_id=?",
            (status, _dump(response), key, user_id),
        )

    def fail(self, key: str, user_id: str) -> None:
        self.db.execute(
            "UPDATE idempotency_keys SET state='failed' WHERE key=? AND user_id=?",
            (key, user_id),
        )

    # FIX-12-CLEANUP
    def delete_older_than(self, cutoff: datetime) -> int:
        cur = self.db.execute(
            "DELETE FROM idempotency_keys WHERE created_at < ?",
            (format_ts(cutoff),),
        )
        return int(cur.rowcount or 0)

    def stats(self) -> dict[str, object]:
        total = int(self.db.scalar("SELECT COUNT(*) FROM idempotency_keys") or 0)
        rows = self.db.query(
            "SELECT state, COUNT(*) AS n FROM idempotency_keys GROUP BY state"
        )
        by_state = {row["state"]: int(row["n"]) for row in rows}
        return {
            "total": total,
            "by_state": by_state,
            "oldest": self.db.scalar("SELECT MIN(created_at) FROM idempotency_keys"),
            "newest": self.db.scalar("SELECT MAX(created_at) FROM idempotency_keys"),
        }


class AccountRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, snapshot: AccountSnapshot) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO account_snapshots (snapshot_id, account_id, taken_at, payload) VALUES (?, ?, ?, ?)",
            (snapshot.snapshot_id, snapshot.account_id, format_ts(snapshot.taken_at), _dump(snapshot.to_dict())),
        )

    def get(self, snapshot_id: str) -> AccountSnapshot | None:
        row = self.db.query_one("SELECT payload FROM account_snapshots WHERE snapshot_id=?", (snapshot_id,))
        return _account_from_dict(_load(row["payload"])) if row else None

    def latest(self, account_id: str) -> AccountSnapshot | None:
        row = self.db.query_one("SELECT payload FROM account_snapshots WHERE account_id=? ORDER BY taken_at DESC LIMIT 1",
                                (account_id,))
        return _account_from_dict(_load(row["payload"])) if row else None


def _account_from_dict(data: dict[str, Any]) -> AccountSnapshot:
    positions = tuple(
        Position(
            position_id=item["position_id"], instrument_id=item["instrument_id"], side=Side(item["side"]),
            volume=to_decimal(item["volume"]), entry_price=to_decimal(item["entry_price"]),
            current_price=to_decimal(item["current_price"]),
            stop_loss=to_decimal(item["stop_loss"]) if item.get("stop_loss") else None,
            take_profit=to_decimal(item["take_profit"]) if item.get("take_profit") else None,
            swap=to_decimal(item.get("swap", "0")), commission=to_decimal(item.get("commission", "0")),
        )
        for item in data.get("positions", [])
    )
    return AccountSnapshot(
        snapshot_id=data["snapshot_id"], account_id=data["account_id"], currency=data["currency"],
        balance=to_decimal(data["balance"]), equity=to_decimal(data["equity"]),
        free_margin=to_decimal(data["free_margin"]), margin_used=to_decimal(data["margin_used"]),
        peak_equity=to_decimal(data["peak_equity"]), daily_pnl=to_decimal(data["daily_pnl"]),
        leverage=to_decimal(data["leverage"]), open_positions=int(data["open_positions"]),
        taken_at=parse_ts(data["taken_at"]), positions=positions,
        max_daily_loss=to_decimal(data["max_daily_loss"]) if data.get("max_daily_loss") else None,
        max_drawdown=to_decimal(data["max_drawdown"]) if data.get("max_drawdown") else None,
    )


class OrderRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save_intent(self, intent: OrderIntent) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO order_intents (intent_id, client_order_id, risk_decision_id, instrument_id, status, created_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (intent.intent_id, intent.client_order_id, intent.risk_decision_id, intent.instrument_id,
             intent.status.value, format_ts(intent.created_at), _dump(intent.to_dict())),
        )

    def get_intent(self, intent_id: str) -> OrderIntent | None:
        row = self.db.query_one("SELECT payload FROM order_intents WHERE intent_id=?", (intent_id,))
        return OrderIntent.from_dict(_load(row["payload"])) if row else None

    def find_by_client_id(self, client_order_id: str) -> OrderIntent | None:
        row = self.db.query_one("SELECT payload FROM order_intents WHERE client_order_id=?", (client_order_id,))
        return OrderIntent.from_dict(_load(row["payload"])) if row else None

    def list_intents_by_status(self, status: OrderStatus, *, limit: int = 500) -> list[OrderIntent]:
        """P6-1: Find intents by status (used by ReconciliationService)."""
        rows = self.db.query(
            "SELECT payload FROM order_intents WHERE status=? ORDER BY created_at LIMIT ?",
            (status.value, limit),
        )
        return [OrderIntent.from_dict(_load(row["payload"])) for row in rows]

    def save_broker_order(self, order: BrokerOrder) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO broker_orders (broker_order_id, intent_id, status, updated_at, payload) VALUES (?, ?, ?, ?, ?)",
            (order.broker_order_id, order.intent_id, order.status.value, format_ts(order.updated_at), _dump(order.to_dict())),
        )

    def get_broker_order(self, broker_order_id: str) -> BrokerOrder | None:
        row = self.db.query_one("SELECT payload FROM broker_orders WHERE broker_order_id=?", (broker_order_id,))
        if row is None:
            return None
        data = _load(row["payload"])
        return BrokerOrder(
            broker_order_id=data["broker_order_id"], intent_id=data["intent_id"], status=OrderStatus(data["status"]),
            symbol=data["symbol"], requested_volume=to_decimal(data["requested_volume"]),
            filled_volume=to_decimal(data["filled_volume"]),
            average_price=to_decimal(data["average_price"]) if data.get("average_price") else None,
            updated_at=parse_ts(data["updated_at"]), message=data.get("message", ""),
        )

    def save_fill(self, fill: Fill) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO fills (fill_id, broker_order_id, filled_at, payload) VALUES (?, ?, ?, ?)",
            (fill.fill_id, fill.broker_order_id, format_ts(fill.filled_at), _dump(fill.to_dict())),
        )


class ModelRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, record: ModelRecord) -> None:
        self.db.execute("INSERT OR REPLACE INTO model_registry (model_id, version, status, payload) VALUES (?, ?, ?, ?)",
                        (record.model_id, record.version, record.status, _dump(record.to_dict())))

    def list(self) -> list[ModelRecord]:
        rows = self.db.query("SELECT payload FROM model_registry ORDER BY model_id, version")
        records: list[ModelRecord] = []
        for row in rows:
            data = _load(row["payload"])
            data["approved_at"] = parse_ts(data["approved_at"]) if data.get("approved_at") else None
            records.append(ModelRecord(**data))
        return records


class LockedTestRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, access_id: str, run_id: str, actor: str, purpose: str, opened_at: datetime) -> None:
        self.db.execute(
            "INSERT INTO locked_test_access (access_id, run_id, opened_at, actor, purpose) VALUES (?, ?, ?, ?, ?)",
            (access_id, run_id, format_ts(opened_at), actor, purpose),
        )

    def list(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.db.query("SELECT * FROM locked_test_access ORDER BY opened_at")]


class RawPayloadRepository:
    """داده خام فقط‌افزودنی برای Lineage و بازتولید (بخش ۶-۶)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def store(self, source_id: str, kind: str, content: bytes, *, meta: dict[str, Any] | None = None,
              received_at: datetime | None = None) -> str:
        from fxars.core.hashing import sha256_bytes

        content_hash = sha256_bytes(content)
        payload_id = stable_id("raw", source_id, kind, content_hash)
        self.db.execute(
            "INSERT OR IGNORE INTO raw_payloads (payload_id, source_id, kind, content_hash, received_at, payload, meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (payload_id, source_id, kind, content_hash, format_ts(received_at or utcnow()),
             content.decode("utf-8", errors="replace"), _dump(meta or {})),
        )
        return payload_id

    def get(self, payload_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM raw_payloads WHERE payload_id=?", (payload_id,))
        if row is None:
            return None
        return {
            "payload_id": row["payload_id"], "source_id": row["source_id"], "kind": row["kind"],
            "content_hash": row["content_hash"], "received_at": row["received_at"],
            "payload": row["payload"], "meta": _load(row["meta"]),
        }

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM raw_payloads") or 0)
