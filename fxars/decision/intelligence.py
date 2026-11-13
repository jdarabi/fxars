"""قابلیت‌های اطلاعاتی تصمیم — بخش ۱۱ سند تکمیلی ۱.۱.

این ماژول پنج قابلیت محصول را پیاده می‌کند:
- دفتر تصمیم (Decision Journal): ثبت روایت تصمیم و بازخورد اپراتور.
- بازپخش خلاف واقع (Counterfactual Replay): «اگر وارد می‌شدیم چه می‌شد؟»
- پیش‌مرگ (Pre-mortem): فرضیه‌های شکست پیش از وقوع.
- نقشه حرارتی سناریوها (Scenario Heatmap): تجمع جهت‌ها و تراکم موقعیت.
- چالش سناریو (Challenge Mode): نقد مستقل ثبت‌شده روی سناریو.

همه خروجی‌ها قطعی و قابل تکرارند؛ شناسه‌ها از محتوای ورودی ساخته می‌شوند.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from fxars.audit.audit import AuditAction
from fxars.core.errors import NotFoundError, ValidationError
from fxars.core.ids import stable_id
from fxars.core.numerics import to_decimal
from fxars.core.timeutil import format_ts, parse_ts, utcnow
from fxars.domain.models import AnalysisRun, Candle, Scenario
from fxars.storage.db import Database

JOURNAL_KINDS = {
    "NOTE", "HYPOTHESIS", "OUTCOME", "REVIEW", "OVERRIDE", "LESSON",
}
SEVERITIES = ("LOW", "MEDIUM", "HIGH")


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


# --------------------------------------------------------------------------- دفتر تصمیم
@dataclass(frozen=True)
class JournalEntry:
    entry_id: str
    tenant_id: str
    kind: str
    actor: str
    created_at: datetime
    analysis_run_id: str | None = None
    scenario_id: str | None = None
    decision_id: str | None = None
    body: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "tenant_id": self.tenant_id,
            "analysis_run_id": self.analysis_run_id,
            "scenario_id": self.scenario_id,
            "decision_id": self.decision_id,
            "kind": self.kind,
            "actor": self.actor,
            "created_at": format_ts(self.created_at),
            "body": self.body,
            "payload": self.payload,
        }


class DecisionJournal:
    def __init__(self, db: Database, audit, clock: Callable[[], datetime] | None = None) -> None:
        self.db = db
        self.audit = audit
        self.clock = clock or utcnow

    def add(
        self,
        *,
        kind: str,
        body: str,
        actor: str,
        analysis_run_id: str | None = None,
        scenario_id: str | None = None,
        decision_id: str | None = None,
        tenant_id: str = "default",
        payload: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> JournalEntry:
        normalized = str(kind or "").strip().upper()
        if normalized not in JOURNAL_KINDS:
            raise ValidationError(f"نوع یادداشت دفتر تصمیم نامعتبر است: {kind}")
        if not str(body or "").strip():
            raise ValidationError("متن یادداشت دفتر تصمیم خالی است.")
        if not str(actor or "").strip():
            raise ValidationError("ثبت یادداشت نیازمند actor است.")
        when = occurred_at or self.clock()
        entry_id = stable_id(
            "dj", tenant_id, normalized, analysis_run_id or "", scenario_id or "",
            decision_id or "", format_ts(when), str(body), length=24,
        )
        existing = self.db.query_one(
            "SELECT payload FROM decision_journal WHERE entry_id = ?", (entry_id,)
        )
        if existing is not None:
            return self._decode(existing)
        entry = JournalEntry(
            entry_id=entry_id,
            tenant_id=tenant_id,
            kind=normalized,
            actor=actor,
            created_at=when,
            analysis_run_id=analysis_run_id,
            scenario_id=scenario_id,
            decision_id=decision_id,
            body=str(body),
            payload=dict(payload or {}),
        )
        self.db.execute(
            "INSERT INTO decision_journal "
            "(entry_id, tenant_id, analysis_run_id, scenario_id, decision_id, kind, actor, created_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.entry_id, entry.tenant_id, entry.analysis_run_id, entry.scenario_id,
                entry.decision_id, entry.kind, entry.actor, format_ts(entry.created_at),
                _dump(entry.to_dict()),
            ),
        )
        self.audit.append(
            AuditAction.DECISION_JOURNAL_RECORDED,
            "decision_journal",
            entry.entry_id,
            actor=actor,
            payload={"kind": normalized, "scenario_id": scenario_id, "run_id": analysis_run_id},
        )
        return entry

    def list(
        self,
        *,
        tenant_id: str | None = "default",
        analysis_run_id: str | None = None,
        scenario_id: str | None = None,
        limit: int = 200,
    ) -> list[JournalEntry]:
        clauses: list[str] = []
        params: list[Any] = []
        if tenant_id is not None:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        if analysis_run_id is not None:
            clauses.append("analysis_run_id = ?")
            params.append(analysis_run_id)
        if scenario_id is not None:
            clauses.append("scenario_id = ?")
            params.append(scenario_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.query(
            f"SELECT payload FROM decision_journal{where} ORDER BY created_at DESC LIMIT ?",
            (*params, int(limit)),
        )
        return [self._decode(row) for row in rows]

    @staticmethod
    def _decode(row: Any) -> JournalEntry:
        data = json.loads(row["payload"])
        return JournalEntry(
            entry_id=data["entry_id"],
            tenant_id=data.get("tenant_id", "default"),
            kind=data["kind"],
            actor=data["actor"],
            created_at=parse_ts(data["created_at"]),
            analysis_run_id=data.get("analysis_run_id"),
            scenario_id=data.get("scenario_id"),
            decision_id=data.get("decision_id"),
            body=data.get("body", ""),
            payload=data.get("payload", {}),
        )


# --------------------------------------------------------------------------- بازپخش خلاف واقع
@dataclass(frozen=True)
class ReplayResult:
    label: str
    direction: str
    entry: str
    stop: str
    target: str
    outcome: str
    r_multiple: float
    bars_held: int
    max_favorable_pips: float
    max_adverse_pips: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "direction": self.direction,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "outcome": self.outcome,
            "r_multiple": round(self.r_multiple, 4),
            "bars_held": self.bars_held,
            "max_favorable_pips": round(self.max_favorable_pips, 2),
            "max_adverse_pips": round(self.max_adverse_pips, 2),
            "note": self.note,
        }


def _scenario_levels(scenario: Scenario) -> tuple[Decimal, Decimal, Decimal] | None:
    entry_raw = scenario.entry_condition.get("level")
    stop = scenario.stop_level
    if entry_raw is None or stop is None:
        return None
    entry = to_decimal(entry_raw)
    if entry <= 0 or stop <= 0:
        return None
    target = None
    for item in scenario.target_logic:
        price = item.get("price")
        if price is not None:
            target = to_decimal(price)
            break
    if target is None or target <= 0:
        return None
    if scenario.direction.value == "LONG" and not (stop < entry < target):
        return None
    if scenario.direction.value == "SHORT" and not (target < entry < stop):
        return None
    return entry, stop, target


def _simulate(
    candles: Sequence[Candle],
    *,
    direction: str,
    entry: Decimal,
    stop: Decimal,
    target: Decimal,
    pip_size: Decimal,
    max_bars: int,
) -> tuple[str, float, int, float, float]:
    risk = abs(entry - stop)
    if risk <= 0:
        return "INVALID", 0.0, 0, 0.0, 0.0
    reward = abs(target - entry)
    r_target = float(reward / risk)
    longest_fav = 0.0
    longest_adv = 0.0
    for index, candle in enumerate(candles[:max_bars]):
        if direction == "LONG":
            favourable = (candle.high - entry) / pip_size
            adverse = (entry - candle.low) / pip_size
            stop_hit = candle.low <= stop
            target_hit = candle.high >= target
        else:
            favourable = (entry - candle.low) / pip_size
            adverse = (candle.high - entry) / pip_size
            stop_hit = candle.high >= stop
            target_hit = candle.low <= target
        longest_fav = max(longest_fav, float(favourable))
        longest_adv = max(longest_adv, float(adverse))
        if stop_hit and target_hit:
            return "STOP_FIRST", -1.0, index + 1, longest_fav, longest_adv
        if stop_hit:
            return "STOP", -1.0, index + 1, longest_fav, longest_adv
        if target_hit:
            return "TARGET", r_target, index + 1, longest_fav, longest_adv
    return "OPEN", 0.0, len(candles[:max_bars]), longest_fav, longest_adv


def replay_scenario(
    scenario: Scenario,
    candles: Sequence[Candle],
    *,
    pip_size: Decimal,
    max_bars: int = 24,
    entry_skip_bars: int = 0,
) -> dict[str, Any]:
    """بازپخش خلاف واقع سناریو روی کندل‌های پس از تصمیم.

    سه حالت گزارش می‌شود: سناریوی اصلی، جهت معکوس (با همان فاصله ریسک) و
    عدم معامله (مرجع صفر). این تابع فقط خواندنی است و تغییری در وضعیت نمی‌دهد.
    """
    levels = _scenario_levels(scenario)
    if levels is None:
        return {"ok": False, "reason": "SCENARIO_LEVELS_INVALID", "variants": []}
    entry, stop, target = levels
    horizon = list(candles)[max(0, int(entry_skip_bars)):]
    if not horizon:
        return {"ok": False, "reason": "NO_FORWARD_CANDLES", "variants": []}
    direction = scenario.direction.value
    primary = _simulate(
        horizon, direction=direction, entry=entry, stop=stop, target=target,
        pip_size=pip_size, max_bars=max_bars,
    )
    risk_distance = abs(entry - stop)
    reward_distance = abs(target - entry)
    if direction == "LONG":
        reverse_stop = entry + risk_distance
        reverse_target = entry - reward_distance if reward_distance > 0 else entry - risk_distance * Decimal("1.5")
    else:
        reverse_stop = entry - risk_distance
        reverse_target = entry + reward_distance if reward_distance > 0 else entry + risk_distance * Decimal("1.5")
    reversed_result = _simulate(
        horizon, direction=("SHORT" if direction == "LONG" else "LONG"),
        entry=entry, stop=reverse_stop, target=reverse_target,
        pip_size=pip_size, max_bars=max_bars,
    )
    variants = [
        ReplayResult(
            label="SCENARIO", direction=direction, entry=str(entry), stop=str(stop),
            target=str(target), outcome=primary[0], r_multiple=primary[1],
            bars_held=primary[2], max_favorable_pips=primary[3], max_adverse_pips=primary[4],
        ).to_dict(),
        ReplayResult(
            label="REVERSED", direction=("SHORT" if direction == "LONG" else "LONG"),
            entry=str(entry), stop=str(reverse_stop), target=str(reverse_target),
            outcome=reversed_result[0], r_multiple=reversed_result[1],
            bars_held=reversed_result[2], max_favorable_pips=reversed_result[3],
            max_adverse_pips=reversed_result[4],
            note="همان نقطه ورود با جهت معکوس و فاصله ریسک برابر.",
        ).to_dict(),
        ReplayResult(
            label="NO_TRADE", direction="NEUTRAL", entry=str(entry), stop=str(stop),
            target=str(target), outcome="NO_TRADE", r_multiple=0.0, bars_held=0,
            max_favorable_pips=0.0, max_adverse_pips=0.0,
            note="مرجع صفر برای مقایسه.",
        ).to_dict(),
    ]
    return {
        "ok": True,
        "scenario_id": scenario.scenario_id,
        "max_bars": int(max_bars),
        "samples": len(horizon[:max_bars]),
        "variants": variants,
    }


# --------------------------------------------------------------------------- پیش‌مرگ
def premortem(run: AnalysisRun) -> list[dict[str, Any]]:
    """فرضیه‌های شکست پیش از وقوع بر پایه همان شواهد تصمیم."""
    payload = run.decision or {}
    meta = payload.get("analysis_meta", {}) or {}
    trust = meta.get("data_trust", {}) or {}
    uncertainty = meta.get("uncertainty", {}) or {}
    graph = meta.get("evidence_graph", {}) or {}
    findings: list[dict[str, Any]] = []

    def add(risk: str, severity: str, detail: str) -> None:
        findings.append({"risk": risk, "severity": severity, "detail": detail})

    trust_score = float(trust.get("score", 1.0) or 0.0)
    if trust_score < 0.8:
        add(
            "DATA_FRAGILITY",
            "HIGH" if trust_score < 0.6 else "MEDIUM",
            f"اعتماد داده {trust_score:.0%} است؛ کیفیت پایین داده می‌تواند منجر به سیگنال کاذب شود.",
        )
    total = float(uncertainty.get("total", 0.0) or 0.0)
    threshold = float(uncertainty.get("wait_threshold", 0.45) or 0.45)
    if total >= threshold:
        add(
            "UNCERTAINTY_HIGH",
            "HIGH" if float(uncertainty.get("max_total", 0.60) or 0.6) - total <= 0.05 else "MEDIUM",
            f"بودجه عدم‌قطعیت {total:.0%} نزدیک یا بالاتر از آستانه {threshold:.0%} است.",
        )
    components = uncertainty.get("components", {}) or {}
    worst = sorted(
        ((name, float(value or 0.0)) for name, value in components.items()),
        key=lambda item: item[1], reverse=True,
    )[:2]
    for name, value in worst:
        if value >= 0.4:
            add(
                f"UNCERTAINTY_{name.upper()}",
                "MEDIUM",
                f"مؤلفه عدم‌قطعیت «{name}» مقدار {value:.0%} دارد و بزرگ‌ترین منبع ریسک شناختی است.",
            )
    conflicts = payload.get("conflicts") or []
    if conflicts:
        add(
            "EVIDENCE_CONFLICT",
            "MEDIUM" if len(conflicts) == 1 else "HIGH",
            "خانواده‌های شواهد ناهم‌راستا هستند: " + ", ".join(str(item) for item in conflicts),
        )
    coverage = float(payload.get("coverage", 1.0) or 0.0)
    if coverage < 0.4:
        add(
            "LOW_COVERAGE",
            "MEDIUM",
            f"پوشش شواهد فقط {coverage:.0%} است؛ تصمیم بر تعداد کمی خانواده استوار است.",
        )
    stability = float(payload.get("stability", 1.0) or 0.0)
    if stability < 0.66:
        add(
            "LOW_STABILITY",
            "MEDIUM",
            f"پایداری سیگنال {stability:.0%} است؛ احتمال تغییر رژیم بین کندل‌ها وجود دارد.",
        )
    direction_summary = graph.get("direction_summary", {}) or {}
    longs = int(direction_summary.get("LONG", 0) or 0)
    shorts = int(direction_summary.get("SHORT", 0) or 0)
    if longs and shorts:
        add(
            "MIXED_DIRECTION",
            "LOW",
            f"شواهد گراف هر دو جهت را نشان می‌دهند (LONG={longs}، SHORT={shorts}).",
        )
    reason = str(payload.get("no_trade_reason") or "")
    if reason:
        add("NO_TRADE_GATE", "LOW", f"دروازه فعال بوده است: {reason}")
    return findings


# --------------------------------------------------------------------------- نقشه حرارتی
def scenario_heatmap(scenarios: Sequence[Scenario]) -> dict[str, Any]:
    """تجمع سناریوهای زنده بر اساس نماد/تایم‌فریم/جهت و هشدار تراکم."""
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for scenario in scenarios:
        if not scenario.status.is_live:
            continue
        key = (scenario.instrument_id, scenario.timeframe)
        bucket = buckets.setdefault(
            key,
            {
                "instrument_id": scenario.instrument_id,
                "timeframe": scenario.timeframe,
                "LONG": 0,
                "SHORT": 0,
                "strength_sum": 0.0,
                "nearest_expiry": scenario.expiry_at,
                "scenario_ids": [],
            },
        )
        bucket[scenario.direction.value] = bucket.get(scenario.direction.value, 0) + 1
        bucket["strength_sum"] += float(scenario.strength or 0.0)
        bucket["scenario_ids"].append(scenario.scenario_id)
        if scenario.expiry_at < bucket["nearest_expiry"]:
            bucket["nearest_expiry"] = scenario.expiry_at
    rows: list[dict[str, Any]] = []
    for bucket in buckets.values():
        count = int(bucket["LONG"]) + int(bucket["SHORT"])
        avg_strength = bucket["strength_sum"] / count if count else 0.0
        crowding = "CROWDED" if count >= 2 and bucket["LONG"] and bucket["SHORT"] else (
            "STACKED" if count >= 2 else "NORMAL"
        )
        rows.append(
            {
                "instrument_id": bucket["instrument_id"],
                "timeframe": bucket["timeframe"],
                "LONG": int(bucket["LONG"]),
                "SHORT": int(bucket["SHORT"]),
                "count": count,
                "avg_strength": round(avg_strength, 4),
                "nearest_expiry": format_ts(bucket["nearest_expiry"]),
                "crowding": crowding,
                "scenario_ids": list(bucket["scenario_ids"]),
            }
        )
    rows.sort(key=lambda item: (item["instrument_id"], item["timeframe"]))
    return {"rows": rows, "total": sum(item["count"] for item in rows)}


# --------------------------------------------------------------------------- چالش سناریو
@dataclass(frozen=True)
class ScenarioChallenge:
    challenge_id: str
    scenario_id: str
    tenant_id: str
    actor: str
    created_at: datetime
    thesis: str
    evidence: tuple[str, ...]
    severity: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "scenario_id": self.scenario_id,
            "tenant_id": self.tenant_id,
            "actor": self.actor,
            "created_at": format_ts(self.created_at),
            "thesis": self.thesis,
            "evidence": list(self.evidence),
            "severity": self.severity,
        }


class ChallengeService:
    def __init__(self, db: Database, audit, clock: Callable[[], datetime] | None = None) -> None:
        self.db = db
        self.audit = audit
        self.clock = clock or utcnow

    def add(
        self,
        scenario_id: str,
        *,
        thesis: str,
        actor: str,
        evidence: Sequence[str] = (),
        severity: str = "MEDIUM",
        tenant_id: str = "default",
    ) -> ScenarioChallenge:
        if not str(thesis or "").strip():
            raise ValidationError("متن چالش سناریو خالی است.")
        level = str(severity or "MEDIUM").upper()
        if level not in SEVERITIES:
            raise ValidationError(f"شدت چالش نامعتبر است: {severity}")
        when = self.clock()
        challenge_id = stable_id(
            "ch", tenant_id, scenario_id, str(thesis), level, format_ts(when), length=24,
        )
        existing = self.db.query_one(
            "SELECT payload FROM scenario_challenges WHERE challenge_id = ?", (challenge_id,)
        )
        if existing is not None:
            return self._decode(existing)
        challenge = ScenarioChallenge(
            challenge_id=challenge_id,
            scenario_id=scenario_id,
            tenant_id=tenant_id,
            actor=actor,
            created_at=when,
            thesis=str(thesis),
            evidence=tuple(str(item) for item in evidence),
            severity=level,
        )
        self.db.execute(
            "INSERT INTO scenario_challenges "
            "(challenge_id, scenario_id, tenant_id, created_at, actor, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                challenge.challenge_id, challenge.scenario_id, challenge.tenant_id,
                format_ts(challenge.created_at), challenge.actor, _dump(challenge.to_dict()),
            ),
        )
        self.audit.append(
            AuditAction.SCENARIO_CHALLENGED,
            "scenario",
            scenario_id,
            actor=actor,
            payload={"challenge_id": challenge.challenge_id, "severity": level},
        )
        return challenge

    def list(self, scenario_id: str, *, limit: int = 100) -> list[ScenarioChallenge]:
        rows = self.db.query(
            "SELECT payload FROM scenario_challenges WHERE scenario_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (scenario_id, int(limit)),
        )
        return [self._decode(row) for row in rows]

    def get(self, challenge_id: str) -> ScenarioChallenge:
        row = self.db.query_one(
            "SELECT payload FROM scenario_challenges WHERE challenge_id = ?", (challenge_id,)
        )
        if row is None:
            raise NotFoundError(f"چالش سناریو یافت نشد: {challenge_id}")
        return self._decode(row)

    @staticmethod
    def _decode(row: Any) -> ScenarioChallenge:
        data = json.loads(row["payload"])
        return ScenarioChallenge(
            challenge_id=data["challenge_id"],
            scenario_id=data["scenario_id"],
            tenant_id=data.get("tenant_id", "default"),
            actor=data["actor"],
            created_at=parse_ts(data["created_at"]),
            thesis=data.get("thesis", ""),
            evidence=tuple(data.get("evidence", ())),
            severity=data.get("severity", "MEDIUM"),
        )
