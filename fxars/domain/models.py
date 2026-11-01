"""موجودیت‌ها و ارزش‌های دامنه.

قواعد:
* قیمت/پول/حجم/نرخ همیشه Decimal هستند.
* همه زمان‌ها UTC و timezone-aware هستند.
* موجودیت‌ها تغییرناپذیرند؛ گذار وضعیت با نمونه جدید + ثبت Transition انجام می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from fxars.core.context import current_correlation_id
from fxars.core.hashing import sha256_obj
from fxars.core.ids import stable_id
from fxars.core.numerics import ZERO, quantize, to_decimal
from fxars.core.serde import jsonable
from fxars.core.timeutil import ensure_utc, format_ts, parse_ts
from fxars.domain.enums import (
    AnalysisStatus,
    BacktestSegment,
    DecisionAction,
    Direction,
    EventImportance,
    EvidenceFamily,
    OrderStatus,
    OrderType,
    Phase,
    QualityStatus,
    RiskReasonCode,
    Role,
    ScenarioStatus,
    SessionName,
    Side,
    Timeframe,
)


# --------------------------------------------------------------------------- ارزش‌ها
def _dt(value: datetime | str) -> datetime:
    return parse_ts(value) if isinstance(value, str) else ensure_utc(value)


@dataclass(frozen=True, slots=True)
class PriceZone:
    low: Decimal
    high: Decimal

    def __post_init__(self) -> None:
        low = to_decimal(self.low, field="zone.low")
        high = to_decimal(self.high, field="zone.high")
        if low > high:
            raise ValueError("محدوده قیمت نامعتبر است: low > high")
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "high", high)

    @property
    def width(self) -> Decimal:
        return self.high - self.low

    @property
    def mid(self) -> Decimal:
        return (self.high + self.low) / 2

    def contains(self, price: Decimal) -> bool:
        return self.low <= price <= self.high

    def overlaps(self, other: "PriceZone") -> bool:
        return self.low <= other.high and other.low <= self.high

    def to_dict(self) -> dict[str, str]:
        return {"low": format(self.low, "f"), "high": format(self.high, "f")}


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_id: str
    symbol: str
    base_currency: str
    quote_currency: str
    digits: int
    point: Decimal
    pip_size: Decimal
    contract_size: Decimal
    min_lot: Decimal
    lot_step: Decimal
    max_lot: Decimal
    tick_size: Decimal
    tick_value: Decimal
    profit_currency: str
    margin_rate: Decimal
    stop_level_points: int
    freeze_level_points: int
    swap_long: Decimal
    swap_short: Decimal
    commission_per_lot: Decimal
    version: int = 1
    source: str = "seed"
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("point", "pip_size", "contract_size", "min_lot", "lot_step", "max_lot",
                     "tick_size", "tick_value", "margin_rate", "swap_long", "swap_short", "commission_per_lot"):
            object.__setattr__(self, name, to_decimal(getattr(self, name), field=name))
        if self.digits < 0:
            raise ValueError("digits باید نامنفی باشد")
        for name in ("point", "pip_size", "contract_size", "min_lot", "lot_step", "tick_size"):
            if getattr(self, name) <= ZERO:
                raise ValueError(f"{name} باید مثبت باشد")
        if self.max_lot < self.min_lot:
            raise ValueError("max_lot نباید کمتر از min_lot باشد")
        if self.valid_from is not None:
            object.__setattr__(self, "valid_from", _dt(self.valid_from))
        if self.valid_to is not None:
            object.__setattr__(self, "valid_to", _dt(self.valid_to))

    def is_valid_at(self, moment: datetime) -> bool:
        moment = ensure_utc(moment)
        if self.valid_from and moment < self.valid_from:
            return False
        if self.valid_to and moment > self.valid_to:
            return False
        return True

    @property
    def price_quantum(self) -> Decimal:
        return Decimal(1).scaleb(-self.digits)

    def round_price(self, value: Decimal) -> Decimal:
        return quantize(value, self.digits)

    @property
    def pip_value_per_lot_quote(self) -> Decimal:
        """ارزش یک پیپ برای یک لات بر حسب ارز مظنه."""
        return self.pip_size * self.contract_size

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Instrument":
        payload = {key: value for key, value in data.items() if value is not None}
        if payload.get("valid_from"):
            payload["valid_from"] = parse_ts(payload["valid_from"])
        if payload.get("valid_to"):
            payload["valid_to"] = parse_ts(payload["valid_to"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class DataSource:
    source_id: str
    name: str
    kind: str
    license_id: str
    redistribution_allowed: bool
    retention_days: int
    timezone: str = "UTC"
    priority: int = 100
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


# --------------------------------------------------------------------------- بازار
@dataclass(frozen=True, slots=True)
class Candle:
    instrument_id: str
    source_id: str
    timeframe: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    ingested_at: datetime
    available_at: datetime
    is_closed: bool = True
    quality_status: QualityStatus = QualityStatus.VALID
    tick_volume: int | None = None
    spread: Decimal | None = None
    source_revision: str | None = None
    revision: int = 1
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, to_decimal(getattr(self, name), field=name))
        object.__setattr__(self, "open_time", _dt(self.open_time))
        object.__setattr__(self, "ingested_at", _dt(self.ingested_at))
        object.__setattr__(self, "available_at", _dt(self.available_at))
        Timeframe.parse(self.timeframe)
        object.__setattr__(self, "timeframe", Timeframe.parse(self.timeframe).value)
        if isinstance(self.quality_status, str):
            object.__setattr__(self, "quality_status", QualityStatus(self.quality_status))
        if self.available_at < self.open_time:
            raise ValueError("available_at نمی‌تواند قبل از open_time باشد")
        if self.spread is not None:
            spread = to_decimal(self.spread, field="spread")
            if spread < ZERO:
                raise ValueError("spread نامعتبر است")
            object.__setattr__(self, "spread", spread)
        if self.tick_volume is not None and self.tick_volume < 0:
            raise ValueError("tick_volume نامعتبر است")
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags))

    @property
    def close_time(self) -> datetime:
        return self.open_time + Timeframe.parse(self.timeframe).delta

    @property
    def key(self) -> tuple[str, str, str, datetime]:
        return (self.instrument_id, self.source_id, self.timeframe, self.open_time)

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def range(self) -> Decimal:
        return self.high - self.low

    @property
    def body(self) -> Decimal:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> Decimal:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> Decimal:
        return min(self.open, self.close) - self.low

    @property
    def effective_spread(self) -> Decimal:
        return self.spread if self.spread is not None else ZERO

    def hash_payload(self) -> dict[str, Any]:
        """محتوای مؤثر بر تحلیل؛ ingested_at عمداً حذف شده است."""
        return {
            "instrument_id": self.instrument_id,
            "source_id": self.source_id,
            "timeframe": self.timeframe,
            "open_time": self.open_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "tick_volume": self.tick_volume,
            "spread": self.spread,
            "is_closed": self.is_closed,
            "quality_status": self.quality_status,
            "available_at": self.available_at,
            "source_revision": self.source_revision,
        }

    def digest(self) -> str:
        return sha256_obj(self.hash_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "source_id": self.source_id,
            "timeframe": self.timeframe,
            "bar_open_time_utc": format_ts(self.open_time),
            "open": format(self.open, "f"),
            "high": format(self.high, "f"),
            "low": format(self.low, "f"),
            "close": format(self.close, "f"),
            "tick_volume": self.tick_volume,
            "spread": None if self.spread is None else format(self.spread, "f"),
            "is_closed": self.is_closed,
            "quality_status": self.quality_status.value,
            "quality_flags": list(self.quality_flags),
            "source_revision": self.source_revision,
            "revision": self.revision,
            "ingested_at": format_ts(self.ingested_at),
            "available_at": format_ts(self.available_at),
            "close_time_utc": format_ts(self.close_time),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Candle":
        return cls(
            instrument_id=data["instrument_id"],
            source_id=data["source_id"],
            timeframe=data["timeframe"],
            open_time=parse_ts(data.get("bar_open_time_utc") or data["open_time"]),
            open=to_decimal(data["open"]),
            high=to_decimal(data["high"]),
            low=to_decimal(data["low"]),
            close=to_decimal(data["close"]),
            tick_volume=data.get("tick_volume"),
            spread=None if data.get("spread") is None else to_decimal(data["spread"]),
            is_closed=bool(data.get("is_closed", True)),
            quality_status=QualityStatus(data.get("quality_status", "VALID")),
            quality_flags=tuple(data.get("quality_flags") or ()),
            source_revision=data.get("source_revision"),
            revision=int(data.get("revision", 1)),
            ingested_at=parse_ts(data.get("ingested_at") or data.get("bar_open_time_utc") or data["open_time"]),
            available_at=parse_ts(data.get("available_at") or data.get("bar_open_time_utc") or data["open_time"]),
        )


@dataclass(frozen=True, slots=True)
class EconomicEvent:
    event_id: str
    indicator: str
    currency: str
    country: str
    event_time: datetime
    published_at: datetime | None
    available_at: datetime
    importance: EventImportance
    actual: Decimal | None = None
    forecast: Decimal | None = None
    previous: Decimal | None = None
    unit: str = ""
    source_id: str = "seed"
    revision_of: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_time", _dt(self.event_time))
        object.__setattr__(self, "available_at", _dt(self.available_at))
        if self.published_at is not None:
            object.__setattr__(self, "published_at", _dt(self.published_at))
        if isinstance(self.importance, str):
            object.__setattr__(self, "importance", EventImportance(self.importance))
        for name in ("actual", "forecast", "previous"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, to_decimal(value, field=name))

    @property
    def surprise(self) -> Decimal | None:
        if self.actual is None or self.forecast is None:
            return None
        return self.actual - self.forecast

    @property
    def surprise_ratio(self) -> float | None:
        if self.actual is None or self.forecast in (None, ZERO):
            return None
        return float((self.actual - self.forecast) / abs(self.forecast))

    def in_window(self, moment: datetime, before_minutes: int, after_minutes: int) -> bool:
        from datetime import timedelta

        moment = ensure_utc(moment)
        return (
            self.event_time - timedelta(minutes=before_minutes)
            <= moment
            <= self.event_time + timedelta(minutes=after_minutes)
        )

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EconomicEvent":
        return cls(
            event_id=data["event_id"],
            indicator=data["indicator"],
            currency=data["currency"],
            country=data["country"],
            event_time=parse_ts(data["event_time"]),
            published_at=parse_ts(data["published_at"]) if data.get("published_at") else None,
            available_at=parse_ts(data["available_at"]),
            importance=EventImportance(data.get("importance", "MEDIUM")),
            actual=to_decimal(data["actual"]) if data.get("actual") is not None else None,
            forecast=to_decimal(data["forecast"]) if data.get("forecast") is not None else None,
            previous=to_decimal(data["previous"]) if data.get("previous") is not None else None,
            unit=data.get("unit", ""),
            source_id=data.get("source_id", "seed"),
            revision_of=data.get("revision_of"),
        )


@dataclass(frozen=True, slots=True)
class Position:
    position_id: str
    instrument_id: str
    side: Side
    volume: Decimal
    entry_price: Decimal
    current_price: Decimal
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    swap: Decimal = ZERO
    commission: Decimal = ZERO

    def __post_init__(self) -> None:
        for name in ("volume", "entry_price", "current_price", "swap", "commission"):
            object.__setattr__(self, name, to_decimal(getattr(self, name), field=name))
        for name in ("stop_loss", "take_profit"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, to_decimal(getattr(self, name), field=name))
        if isinstance(self.side, str):
            object.__setattr__(self, "side", Side(self.side))

    @property
    def notional_exposure(self) -> Decimal:
        return self.volume * self.entry_price

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    snapshot_id: str
    account_id: str
    currency: str
    balance: Decimal
    equity: Decimal
    free_margin: Decimal
    margin_used: Decimal
    peak_equity: Decimal
    daily_pnl: Decimal
    leverage: Decimal
    open_positions: int
    taken_at: datetime
    positions: tuple[Position, ...] = ()
    max_daily_loss: Decimal | None = None
    max_drawdown: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("balance", "equity", "free_margin", "margin_used", "peak_equity",
                     "daily_pnl", "leverage", "max_daily_loss", "max_drawdown"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, to_decimal(value, field=name))
        object.__setattr__(self, "taken_at", _dt(self.taken_at))
        object.__setattr__(self, "positions", tuple(self.positions))
        if self.equity <= ZERO:
            raise ValueError("equity باید مثبت باشد")

    @property
    def margin_level(self) -> Decimal:
        if self.margin_used <= ZERO:
            return Decimal("0")
        return self.equity / self.margin_used * Decimal(100)

    @property
    def drawdown_fraction(self) -> Decimal:
        if self.peak_equity <= ZERO:
            return ZERO
        return max(ZERO, (self.peak_equity - self.equity) / self.peak_equity)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


# --------------------------------------------------------------------------- تحلیل
@dataclass(frozen=True, slots=True)
class Evidence:
    evidence_id: str
    analysis_run_id: str
    module_id: str
    module_version: str
    instrument_id: str
    timeframe: str
    observed_at: datetime
    available_at: datetime
    direction: Direction
    strength: float
    confidence_raw: float
    family: EvidenceFamily
    explanation: str
    price_zone: PriceZone | None = None
    invalidation: dict[str, Any] | None = None
    expiry: datetime | None = None
    parameters_hash: str = ""
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _dt(self.observed_at))
        object.__setattr__(self, "available_at", _dt(self.available_at))
        if self.expiry is not None:
            object.__setattr__(self, "expiry", _dt(self.expiry))
        if isinstance(self.direction, str):
            object.__setattr__(self, "direction", Direction(self.direction))
        if isinstance(self.family, str):
            object.__setattr__(self, "family", EvidenceFamily(self.family))
        if not 0.0 <= float(self.strength) <= 1.0:
            raise ValueError("strength باید در بازه ۰..۱ باشد")
        if not 0.0 <= float(self.confidence_raw) <= 1.0:
            raise ValueError("confidence_raw باید در بازه ۰..۱ باشد")
        if self.available_at < self.observed_at:
            raise ValueError("available_at نمی‌تواند قبل از observed_at باشد")
        object.__setattr__(self, "source_refs", tuple(self.source_refs))

    @property
    def signed_strength(self) -> float:
        return self.direction.sign * float(self.strength)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "analysis_run_id": self.analysis_run_id,
            "module_id": self.module_id,
            "module_version": self.module_version,
            "family": self.family.value,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "observed_at": format_ts(self.observed_at),
            "available_at": format_ts(self.available_at),
            "direction": self.direction.value,
            "strength": round(float(self.strength), 6),
            "confidence_raw": round(float(self.confidence_raw), 6),
            "price_zone": self.price_zone.to_dict() if self.price_zone else None,
            "invalidation": self.invalidation,
            "expiry": format_ts(self.expiry) if self.expiry else None,
            "parameters_hash": self.parameters_hash,
            "source_refs": list(self.source_refs),
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        zone = data.get("price_zone")
        return cls(
            evidence_id=data["evidence_id"],
            analysis_run_id=data["analysis_run_id"],
            module_id=data["module_id"],
            module_version=data["module_version"],
            family=EvidenceFamily(data["family"]),
            instrument_id=data["instrument_id"],
            timeframe=data["timeframe"],
            observed_at=parse_ts(data["observed_at"]),
            available_at=parse_ts(data["available_at"]),
            direction=Direction(data["direction"]),
            strength=float(data["strength"]),
            confidence_raw=float(data["confidence_raw"]),
            price_zone=PriceZone(zone["low"], zone["high"]) if zone else None,
            invalidation=data.get("invalidation"),
            expiry=parse_ts(data["expiry"]) if data.get("expiry") else None,
            parameters_hash=data.get("parameters_hash", ""),
            source_refs=tuple(data.get("source_refs") or ()),
            explanation=data.get("explanation", ""),
        )


@dataclass(frozen=True, slots=True)
class Decision:
    action: DecisionAction
    direction: Direction
    score: float
    confidence_raw: float
    family_scores: dict[str, float]
    conflicts: tuple[str, ...]
    coverage: float
    stability: float
    reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    no_trade_reason: str | None = None
    strength: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class AnalysisRun:
    run_id: str
    instrument_id: str
    timeframe: str
    as_of: datetime
    data_snapshot_id: str
    config_hash: str
    code_version: str
    model_version: str
    status: AnalysisStatus
    correlation_id: str
    started_at: datetime
    finished_at: datetime | None
    result_hash: str
    evidence_count: int
    decision: dict[str, Any]
    data_quality: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = jsonable(self)
        payload["as_of"] = format_ts(self.as_of)
        payload["started_at"] = format_ts(self.started_at)
        payload["finished_at"] = format_ts(self.finished_at) if self.finished_at else None
        payload["status"] = self.status.value
        return payload


# --------------------------------------------------------------------------- سناریو
@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    instrument_id: str
    timeframe: str
    direction: Direction
    status: ScenarioStatus
    entry_condition: dict[str, Any]
    invalidation_condition: dict[str, Any]
    stop_logic: dict[str, Any]
    target_logic: tuple[dict[str, Any], ...]
    expiry_at: datetime
    evidence_ids: tuple[str, ...]
    analysis_run_id: str
    decision_explanation: str
    created_at: datetime
    updated_at: datetime
    rules_version: str
    config_hash: str
    entry_zone: PriceZone | None = None
    risk_decision_id: str | None = None
    strength: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "expiry_at", _dt(self.expiry_at))
        object.__setattr__(self, "created_at", _dt(self.created_at))
        object.__setattr__(self, "updated_at", _dt(self.updated_at))
        if isinstance(self.direction, str):
            object.__setattr__(self, "direction", Direction(self.direction))
        if isinstance(self.status, str):
            object.__setattr__(self, "status", ScenarioStatus(self.status))
        object.__setattr__(self, "target_logic", tuple(self.target_logic))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        if self.direction is Direction.NEUTRAL:
            raise ValueError("سناریو باید جهت LONG یا SHORT داشته باشد")

    def with_status(self, status: ScenarioStatus, *, when: datetime, risk_decision_id: str | None = None) -> "Scenario":
        return replace(
            self,
            status=status,
            updated_at=_dt(when),
            risk_decision_id=risk_decision_id or self.risk_decision_id,
        )

    @property
    def stop_level(self) -> Decimal | None:
        level = self.stop_logic.get("level")
        return to_decimal(level) if level is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "analysis_run_id": self.analysis_run_id,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "status": self.status.value,
            "direction": self.direction.value,
            "entry_condition": self.entry_condition,
            "entry_zone": self.entry_zone.to_dict() if self.entry_zone else None,
            "invalidation_condition": self.invalidation_condition,
            "stop_logic": self.stop_logic,
            "target_logic": list(self.target_logic),
            "expiry_at": format_ts(self.expiry_at),
            "evidence_ids": list(self.evidence_ids),
            "risk_decision_id": self.risk_decision_id,
            "decision_explanation": self.decision_explanation,
            "created_at": format_ts(self.created_at),
            "updated_at": format_ts(self.updated_at),
            "rules_version": self.rules_version,
            "config_hash": self.config_hash,
            "strength": round(float(self.strength), 6),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scenario":
        zone = data.get("entry_zone")
        return cls(
            scenario_id=data["scenario_id"],
            instrument_id=data["instrument_id"],
            timeframe=data["timeframe"],
            direction=Direction(data["direction"]),
            status=ScenarioStatus(data["status"]),
            entry_condition=data["entry_condition"],
            invalidation_condition=data["invalidation_condition"],
            stop_logic=data["stop_logic"],
            target_logic=tuple(data["target_logic"]),
            expiry_at=parse_ts(data["expiry_at"]),
            evidence_ids=tuple(data["evidence_ids"]),
            analysis_run_id=data.get("analysis_run_id", ""),
            decision_explanation=data.get("decision_explanation", ""),
            created_at=parse_ts(data["created_at"]),
            updated_at=parse_ts(data["updated_at"]),
            rules_version=data.get("rules_version", ""),
            config_hash=data.get("config_hash", ""),
            entry_zone=PriceZone(zone["low"], zone["high"]) if zone else None,
            risk_decision_id=data.get("risk_decision_id"),
            strength=float(data.get("strength", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class ScenarioTransition:
    transition_id: str
    scenario_id: str
    from_status: ScenarioStatus
    to_status: ScenarioStatus
    event: str
    actor: str
    reason: str
    occurred_at: datetime
    rules_version: str
    data_ref: str = ""
    correlation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


# --------------------------------------------------------------------------- ریسک
@dataclass(frozen=True, slots=True)
class RiskCheck:
    code: str
    passed: bool
    detail: str
    value: str | None = None
    limit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision_id: str
    scenario_id: str
    instrument_id: str
    account_snapshot_id: str
    approved: bool
    risk_amount: Decimal
    risk_currency: str
    position_size: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal | None
    checks: tuple[RiskCheck, ...]
    policy_version: str
    reason_code: RiskReasonCode
    reason_detail: str
    valid_until: datetime
    created_at: datetime
    inputs_hash: str
    correlation_id: str = field(default_factory=current_correlation_id)

    def __post_init__(self) -> None:
        for name in ("risk_amount", "position_size", "entry_price", "stop_loss"):
            object.__setattr__(self, name, to_decimal(getattr(self, name), field=name))
        if self.take_profit is not None:
            object.__setattr__(self, "take_profit", to_decimal(self.take_profit, field="take_profit"))
        object.__setattr__(self, "valid_until", _dt(self.valid_until))
        object.__setattr__(self, "created_at", _dt(self.created_at))
        if isinstance(self.reason_code, str):
            object.__setattr__(self, "reason_code", RiskReasonCode(self.reason_code))
        object.__setattr__(self, "checks", tuple(self.checks))

    @property
    def checks_passed(self) -> tuple[str, ...]:
        return tuple(check.code for check in self.checks if check.passed)

    @property
    def checks_failed(self) -> tuple[str, ...]:
        return tuple(check.code for check in self.checks if not check.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "scenario_id": self.scenario_id,
            "instrument_id": self.instrument_id,
            "account_snapshot_id": self.account_snapshot_id,
            "approved": self.approved,
            "risk_amount": format(self.risk_amount, "f"),
            "risk_currency": self.risk_currency,
            "position_size": format(self.position_size, "f"),
            "entry_price": format(self.entry_price, "f"),
            "stop_loss": format(self.stop_loss, "f"),
            "take_profit": format(self.take_profit, "f") if self.take_profit is not None else None,
            "checks_passed": list(self.checks_passed),
            "checks_failed": list(self.checks_failed),
            "checks": [check.to_dict() for check in self.checks],
            "policy_version": self.policy_version,
            "reason_code": self.reason_code.value,
            "reason_detail": self.reason_detail,
            "valid_until": format_ts(self.valid_until),
            "created_at": format_ts(self.created_at),
            "inputs_hash": self.inputs_hash,
            "correlation_id": self.correlation_id,
        }


# --------------------------------------------------------------------------- اجرا (MVP-2+)
@dataclass(frozen=True, slots=True)
class OrderIntent:
    intent_id: str
    client_order_id: str
    risk_decision_id: str
    instrument_id: str
    side: Side
    order_type: OrderType
    volume: Decimal
    stop_loss: Decimal
    take_profit: Decimal | None
    created_at: datetime
    status: OrderStatus
    phase: Phase
    correlation_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "volume", to_decimal(self.volume, field="volume"))
        object.__setattr__(self, "stop_loss", to_decimal(self.stop_loss, field="stop_loss"))
        if self.take_profit is not None:
            object.__setattr__(self, "take_profit", to_decimal(self.take_profit, field="take_profit"))
        object.__setattr__(self, "created_at", _dt(self.created_at))
        if isinstance(self.side, str):
            object.__setattr__(self, "side", Side(self.side))
        if isinstance(self.order_type, str):
            object.__setattr__(self, "order_type", OrderType(self.order_type))
        if isinstance(self.status, str):
            object.__setattr__(self, "status", OrderStatus(self.status))
        if isinstance(self.phase, str):
            object.__setattr__(self, "phase", Phase(self.phase))
        if self.volume <= ZERO:
            raise ValueError("volume باید مثبت باشد")

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "client_order_id": self.client_order_id,
            "risk_decision_id": self.risk_decision_id,
            "instrument_id": self.instrument_id,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "volume": format(self.volume, "f"),
            "stop_loss": format(self.stop_loss, "f"),
            "take_profit": format(self.take_profit, "f") if self.take_profit else None,
            "created_at": format_ts(self.created_at),
            "status": self.status.value,
            "phase": self.phase.value,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrderIntent":
        return cls(
            intent_id=data["intent_id"],
            client_order_id=data["client_order_id"],
            risk_decision_id=data["risk_decision_id"],
            instrument_id=data["instrument_id"],
            side=Side(data["side"]),
            order_type=OrderType(data["order_type"]),
            volume=to_decimal(data["volume"]),
            stop_loss=to_decimal(data["stop_loss"]),
            take_profit=to_decimal(data["take_profit"]) if data.get("take_profit") else None,
            created_at=parse_ts(data["created_at"]),
            status=OrderStatus(data["status"]),
            phase=Phase(data["phase"]),
            correlation_id=data.get("correlation_id", ""),
        )


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    broker_order_id: str
    intent_id: str
    status: OrderStatus
    symbol: str
    requested_volume: Decimal
    filled_volume: Decimal
    average_price: Decimal | None
    updated_at: datetime
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    broker_order_id: str
    volume: Decimal
    price: Decimal
    commission: Decimal
    filled_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


# --------------------------------------------------------------------------- کیفیت داده
@dataclass(frozen=True, slots=True)
class DataQualityIssue:
    rule: str
    severity: str
    message: str
    key: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class DataQualityRun:
    run_id: str
    instrument_id: str
    timeframe: str
    source_id: str
    checked_at: datetime
    total: int
    valid: int
    suspect: int
    invalid: int
    missing: int
    stale: bool
    verdict: str
    issues: tuple[DataQualityIssue, ...]
    latest_bar_age_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "source_id": self.source_id,
            "checked_at": format_ts(self.checked_at),
            "total": self.total,
            "valid": self.valid,
            "suspect": self.suspect,
            "invalid": self.invalid,
            "missing": self.missing,
            "stale": self.stale,
            "verdict": self.verdict,
            "latest_bar_age_seconds": round(self.latest_bar_age_seconds, 3),
            "issues": [issue.to_dict() for issue in self.issues],
        }


# --------------------------------------------------------------------------- هویت
@dataclass(frozen=True, slots=True)
class User:
    user_id: str
    username: str
    role: Role
    password_hash: str
    active: bool
    created_at: datetime
    tenant_id: str = "default"
    totp_secret_enc: str | None = None
    display_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = jsonable(self)
        data.pop("password_hash", None)
        data.pop("totp_secret_enc", None)
        data["mfa_enabled"] = bool(self.totp_secret_enc)
        return data


@dataclass(frozen=True, slots=True)
class SessionRecord:
    token_hash: str
    user_id: str
    created_at: datetime
    expires_at: datetime
    ip: str = ""
    revoked: bool = False

    def is_valid(self, now: datetime) -> bool:
        return not self.revoked and ensure_utc(now) < self.expires_at


@dataclass(frozen=True, slots=True)
class ModelRecord:
    model_id: str
    version: str
    dataset_snapshot: str
    feature_schema: str
    code_hash: str
    config_hash: str
    validation_report: dict[str, Any]
    approved_by: str | None
    approved_at: datetime | None
    status: str = "CANDIDATE"

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


# --------------------------------------------------------------------------- ممیزی و رویداد
@dataclass(frozen=True, slots=True)
class AuditEntry:
    seq: int
    event_id: str
    occurred_at: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    correlation_id: str
    payload: dict[str, Any]
    prev_hash: str
    entry_hash: str

    def to_dict(self) -> dict[str, Any]:
        data = jsonable(self)
        data.pop("seq", None)
        return data


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_id: str
    event_type: str
    schema_version: str
    occurred_at: datetime
    correlation_id: str
    payload: dict[str, Any]
    published_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


# --------------------------------------------------------------------------- پژوهش
@dataclass(frozen=True, slots=True)
class BacktestRun:
    run_id: str
    instrument_id: str
    timeframe: str
    config: dict[str, Any]
    config_hash: str
    data_snapshot_id: str
    code_version: str
    segment: BacktestSegment
    started_at: datetime
    finished_at: datetime
    metrics: dict[str, Any]
    trades: tuple[dict[str, Any], ...]
    equity_curve: tuple[tuple[str, str], ...]
    seed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "config": self.config,
            "config_hash": self.config_hash,
            "data_snapshot_id": self.data_snapshot_id,
            "code_version": self.code_version,
            "segment": self.segment.value,
            "started_at": format_ts(self.started_at),
            "finished_at": format_ts(self.finished_at),
            "seed": self.seed,
            "metrics": self.metrics,
            "trades": list(self.trades),
            "equity_curve": [list(point) for point in self.equity_curve],
        }
