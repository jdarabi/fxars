"""زنجیره منشأ تصمیم — بخش ۷-۳ و ۳-۲ سند تکمیلی ۱.۱.

هر تصمیم یک رکورد تغییرناپذیر با فیلدهای استاندارد دارد و با هش رکورد قبلی
زنجیر می‌شود؛ دستکاری یک رکورد، زنجیره را می‌شکند.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fxars.core.errors import FxarsError, NotFoundError
from fxars.core.hashing import sha256_obj
from fxars.core.ids import stable_id
from fxars.core.timeutil import format_ts, parse_ts, utcnow
from fxars.domain.models import AnalysisRun
from fxars.storage.db import Database

GENESIS = "0" * 64


class ProvenanceError(FxarsError):
    """رکورد منشأ تصمیم ناقص یا زنجیره نامعتبر است."""


REQUIRED_FIELDS = (
    "decision_status",
    "scenario_id",
    "data_cutoff",
    "data_quality_status",
    "regime",
    "evidence_graph_ref",
    "uncertainty_factors",
    "risk_gate_result",
    "config_hash",
    "code_version",
    "model_versions",
    "reason_codes",
)


@dataclass(frozen=True)
class DecisionProvenance:
    record_id: str
    decision_id: str
    analysis_run_id: str
    scenario_id: str | None
    tenant_id: str
    created_at: datetime
    decision_status: str
    no_trade_reason: str | None
    data_cutoff: str
    data_quality_status: str
    regime: str
    evidence_graph_ref: str
    uncertainty_factors: dict[str, Any]
    risk_gate_result: dict[str, Any] | None
    config_hash: str
    code_version: str
    model_versions: dict[str, str]
    reason_codes: tuple[str, ...]
    human_override: dict[str, Any] | None
    prev_hash: str
    record_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "decision_id": self.decision_id,
            "analysis_run_id": self.analysis_run_id,
            "scenario_id": self.scenario_id,
            "tenant_id": self.tenant_id,
            "created_at": format_ts(self.created_at),
            "decision_status": self.decision_status,
            "no_trade_reason": self.no_trade_reason,
            "data_cutoff": self.data_cutoff,
            "data_quality_status": self.data_quality_status,
            "regime": self.regime,
            "evidence_graph_ref": self.evidence_graph_ref,
            "uncertainty_factors": self.uncertainty_factors,
            "risk_gate_result": self.risk_gate_result,
            "config_hash": self.config_hash,
            "code_version": self.code_version,
            "model_versions": self.model_versions,
            "reason_codes": list(self.reason_codes),
            "human_override": self.human_override,
            "prev_hash": self.prev_hash,
            "record_hash": self.record_hash,
        }


@dataclass(frozen=True)
class RecordInput:
    analysis_run_id: str
    decision_id: str
    scenario_id: str | None
    tenant_id: str
    decision_status: str
    no_trade_reason: str | None
    data_cutoff: str
    data_quality_status: str
    regime: str
    evidence_graph_ref: str
    uncertainty_factors: dict[str, Any]
    risk_gate_result: dict[str, Any] | None
    config_hash: str
    code_version: str
    model_versions: dict[str, str]
    reason_codes: tuple[str, ...]
    human_override: dict[str, Any] | None


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


class DecisionProvenanceStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def last(self, *, tenant_id: str | None = None) -> DecisionProvenance | None:
        if tenant_id is None:
            row = self.db.query_one(
                "SELECT payload FROM decision_provenance ORDER BY created_at DESC, record_id DESC LIMIT 1"
            )
        else:
            row = self.db.query_one(
                "SELECT payload FROM decision_provenance WHERE tenant_id = ? "
                "ORDER BY created_at DESC, record_id DESC LIMIT 1",
                (tenant_id,),
            )
        return self._decode(row) if row else None

    def get(self, record_id: str) -> DecisionProvenance:
        row = self.db.query_one(
            "SELECT payload FROM decision_provenance WHERE record_id = ?", (record_id,)
        )
        if row is None:
            raise NotFoundError(f"رکورد منشأ تصمیم یافت نشد: {record_id}")
        return self._decode(row)

    def for_run(self, run_id: str, *, tenant_id: str | None = None) -> list[DecisionProvenance]:
        if tenant_id is None:
            rows = self.db.query(
                "SELECT payload FROM decision_provenance WHERE analysis_run_id = ? "
                "ORDER BY created_at",
                (run_id,),
            )
        else:
            rows = self.db.query(
                "SELECT payload FROM decision_provenance WHERE analysis_run_id = ? AND tenant_id = ? "
                "ORDER BY created_at",
                (run_id, tenant_id),
            )
        return [self._decode(row) for row in rows]

    def list(self, *, tenant_id: str | None = None, limit: int = 100) -> list[DecisionProvenance]:
        if tenant_id is None:
            rows = self.db.query(
                "SELECT payload FROM decision_provenance ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            rows = self.db.query(
                "SELECT payload FROM decision_provenance WHERE tenant_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (tenant_id, limit),
            )
        return [self._decode(row) for row in rows]

    def record(self, data: RecordInput, *, created_at: datetime | None = None) -> DecisionProvenance:
        for name in ("decision_status", "data_cutoff", "data_quality_status", "config_hash", "code_version"):
            if not getattr(data, name):
                raise ProvenanceError(f"فیلد الزامی منشأ تصمیم خالی است: {name}")
        if not data.evidence_graph_ref:
            raise ProvenanceError("فیلد الزامی منشأ تصمیم خالی است: evidence_graph_ref")
        when = created_at or utcnow()
        previous = self.last(tenant_id=data.tenant_id)
        prev_hash = previous.record_hash if previous else GENESIS
        body = {
            "decision_id": data.decision_id,
            "analysis_run_id": data.analysis_run_id,
            "scenario_id": data.scenario_id,
            "tenant_id": data.tenant_id,
            "created_at": format_ts(when),
            "decision_status": data.decision_status,
            "no_trade_reason": data.no_trade_reason,
            "data_cutoff": data.data_cutoff,
            "data_quality_status": data.data_quality_status,
            "regime": data.regime,
            "evidence_graph_ref": data.evidence_graph_ref,
            "uncertainty_factors": data.uncertainty_factors,
            "risk_gate_result": data.risk_gate_result,
            "config_hash": data.config_hash,
            "code_version": data.code_version,
            "model_versions": data.model_versions,
            "reason_codes": list(data.reason_codes),
            "human_override": data.human_override,
        }
        record_hash = sha256_obj({"prev": prev_hash, "body": body})
        record_id = stable_id("dp", data.analysis_run_id, data.decision_id, prev_hash, length=24)
        record = DecisionProvenance(
            record_id=record_id,
            decision_id=data.decision_id,
            analysis_run_id=data.analysis_run_id,
            scenario_id=data.scenario_id,
            tenant_id=data.tenant_id,
            created_at=when,
            decision_status=data.decision_status,
            no_trade_reason=data.no_trade_reason,
            data_cutoff=data.data_cutoff,
            data_quality_status=data.data_quality_status,
            regime=data.regime,
            evidence_graph_ref=data.evidence_graph_ref,
            uncertainty_factors=dict(data.uncertainty_factors),
            risk_gate_result=data.risk_gate_result,
            config_hash=data.config_hash,
            code_version=data.code_version,
            model_versions=dict(data.model_versions),
            reason_codes=tuple(data.reason_codes),
            human_override=data.human_override,
            prev_hash=prev_hash,
            record_hash=record_hash,
        )
        self.db.execute(
            "INSERT INTO decision_provenance "
            "(record_id, decision_id, analysis_run_id, scenario_id, tenant_id, created_at, "
            " prev_hash, record_hash, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.record_id,
                record.decision_id,
                record.analysis_run_id,
                record.scenario_id,
                record.tenant_id,
                format_ts(record.created_at),
                record.prev_hash,
                record.record_hash,
                _dump(record.to_dict()),
            ),
        )
        return record

    def verify_chain(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        rows = self.db.query(
            "SELECT payload FROM decision_provenance "
            + ("WHERE tenant_id = ? " if tenant_id else "")
            + "ORDER BY created_at, record_id",
            ((tenant_id,) if tenant_id else ()),
        )
        prev = GENESIS
        for index, row in enumerate(rows):
            record = self._decode(row)
            body = record.to_dict()
            body.pop("record_hash")
            body.pop("prev_hash")
            body.pop("record_id")
            expected = sha256_obj({"prev": prev, "body": body})
            if record.prev_hash != prev or record.record_hash != expected:
                return {
                    "valid": False,
                    "entries": len(rows),
                    "failed_index": index,
                    "record_id": record.record_id,
                }
            prev = record.record_hash
        return {"valid": True, "entries": len(rows), "head": prev}

    @staticmethod
    def _decode(row: Any) -> DecisionProvenance:
        data = json.loads(row["payload"])
        return DecisionProvenance(
            record_id=data["record_id"],
            decision_id=data["decision_id"],
            analysis_run_id=data["analysis_run_id"],
            scenario_id=data.get("scenario_id"),
            tenant_id=data.get("tenant_id", "default"),
            created_at=parse_ts(data["created_at"]),
            decision_status=data["decision_status"],
            no_trade_reason=data.get("no_trade_reason"),
            data_cutoff=data["data_cutoff"],
            data_quality_status=data["data_quality_status"],
            regime=data.get("regime", "UNKNOWN"),
            evidence_graph_ref=data.get("evidence_graph_ref", ""),
            uncertainty_factors=data.get("uncertainty_factors", {}),
            risk_gate_result=data.get("risk_gate_result"),
            config_hash=data["config_hash"],
            code_version=data["code_version"],
            model_versions=data.get("model_versions", {}),
            reason_codes=tuple(data.get("reason_codes", ())),
            human_override=data.get("human_override"),
            prev_hash=data["prev_hash"],
            record_hash=data["record_hash"],
        )


class ProvenanceService:
    """ساخت رکورد منشأ از نتیجه تحلیل ذخیره‌شده."""

    def __init__(self, store: DecisionProvenanceStore, audit, outbox=None) -> None:
        self.store = store
        self.audit = audit
        self.outbox = outbox

    def record_run(self, run: AnalysisRun, *, actor: str = "system") -> DecisionProvenance:
        payload = run.decision or {}
        meta = payload.get("analysis_meta", {}) if isinstance(payload, dict) else {}
        trust = meta.get("data_trust", {}) or {}
        uncertainty = meta.get("uncertainty", {}) or {}

        scenario_id = payload.get("scenario_id")
        status = str(payload.get("action", "NO_TRADE"))
        no_trade_reason = payload.get("no_trade_reason")
        reasons = [str(no_trade_reason)] if no_trade_reason else [status]
        for item in uncertainty.get("reasons", []) or []:
            code = _reason_code(str(item))
            if code:
                reasons.append(code)
        record = self.store.record(
            RecordInput(
                analysis_run_id=run.run_id,
                decision_id=f"dec_{run.run_id}",
                scenario_id=scenario_id,
                tenant_id=run.tenant_id,
                decision_status=status,
                no_trade_reason=no_trade_reason,
                data_cutoff=format_ts(run.as_of),
                data_quality_status=str(trust.get("status", run.status.value)),
                regime=str((run.data_quality or {}).get("regime", payload.get("trend", "UNKNOWN"))),
                evidence_graph_ref=str(meta.get("graph_id", "") or "eg_none"),
                uncertainty_factors=uncertainty.get("components", {}),
                risk_gate_result=None,
                config_hash=run.config_hash,
                code_version=run.code_version,
                model_versions={"rules": run.model_version or "none"},
                reason_codes=tuple(dict.fromkeys(reasons)),
                human_override=None,
            ),
            created_at=run.finished_at or run.as_of,
        )
        self.audit.append(
            "DECISION_RECORDED",
            "analysis_run",
            run.run_id,
            actor=actor,
            payload={"record_id": record.record_id, "decision_id": record.decision_id},
        )
        return record


def _reason_code(text: str) -> str | None:
    upper = text.upper()
    for code in (
        "DATA_UNTRUSTED",
        "DATA_STALE",
        "UNCERTAINTY",
        "CONFLICT",
        "SPREAD",
        "REGIME",
        "CALIBRATION",
    ):
        if code in upper:
            return code
    return None
