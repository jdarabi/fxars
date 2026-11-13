"""Model Registry و Model Risk Tiering — بخش ۶ سند تکمیلی ۱.۱.

مدل‌ها بر اساس اثر بر تصمیم در چهار رده دسته‌بندی می‌شوند:
- Tier 0: فقط گزارش/تحلیل (پایش پایه)
- Tier 1: شواهد کمکی (کالیبراسیون و بازبینی دوره‌ای)
- Tier 2: اثر مستقیم بر سناریو (OOS، Model Card، تأیید مستقل)
- Tier 3: اثر بر ریسک/اجرا (در MVP ممنوع؛ فقط با حاکمیت و Kill Switch)

گذار وضعیت: DRAFT → SHADOW → CANARY → ACTIVE → RETIRED
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from fxars.audit.audit import AuditAction
from fxars.config.decision import GovernancePolicy
from fxars.core.errors import ConflictError, ValidationError
from fxars.core.hashing import sha256_obj
from fxars.core.timeutil import format_ts, parse_ts, utcnow
from fxars.domain.models import ModelRecord
from fxars.storage.db import Database

STATUSES = ("DRAFT", "SHADOW", "CANARY", "ACTIVE", "RETIRED")
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"SHADOW", "RETIRED"},
    "SHADOW": {"CANARY", "RETIRED"},
    "CANARY": {"ACTIVE", "SHADOW", "RETIRED"},
    "ACTIVE": {"RETIRED"},
    "RETIRED": set(),
}


class ModelTransitionError(ConflictError):
    pass


@dataclass(frozen=True)
class ModelCard:
    model_id: str
    version: str
    tier: int
    purpose: str
    owner: str
    training_data: str
    feature_schema: str
    limitations: tuple[str, ...]
    metrics: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    provides_probability: bool = False
    dataset_snapshot: str = ""
    code_hash: str = ""
    config_hash: str = ""
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: str = "DRAFT"
    approved_by: str | None = None
    approved_at: datetime | None = None
    kill_switch_ready: bool = False
    shadow_completed: bool = False
    oos_passed: bool = False
    independent_approval: bool = False

    def content_hash(self) -> str:
        return sha256_obj(
            {
                "model_id": self.model_id,
                "version": self.version,
                "tier": self.tier,
                "purpose": self.purpose,
                "training_data": self.training_data,
                "feature_schema": self.feature_schema,
                "metrics": self.metrics,
                "calibration": self.calibration,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "tier": self.tier,
            "purpose": self.purpose,
            "owner": self.owner,
            "training_data": self.training_data,
            "feature_schema": self.feature_schema,
            "limitations": list(self.limitations),
            "metrics": self.metrics,
            "calibration": self.calibration,
            "provides_probability": self.provides_probability,
            "dataset_snapshot": self.dataset_snapshot,
            "code_hash": self.code_hash,
            "config_hash": self.config_hash,
            "valid_from": format_ts(self.valid_from) if self.valid_from else None,
            "valid_until": format_ts(self.valid_until) if self.valid_until else None,
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_at": format_ts(self.approved_at) if self.approved_at else None,
            "kill_switch_ready": self.kill_switch_ready,
            "shadow_completed": self.shadow_completed,
            "oos_passed": self.oos_passed,
            "independent_approval": self.independent_approval,
            "content_hash": self.content_hash(),
        }


def validate_model_card(card: ModelCard, policy: GovernancePolicy) -> list[str]:
    errors: list[str] = []
    if card.tier not in (0, 1, 2, 3):
        errors.append("tier باید ۰..۳ باشد.")
    if policy.mvp_tier3_forbidden and card.tier >= 3:
        errors.append("مدل Tier 3 در MVP مجاز نیست؛ فقط با مصوبه حاکمیت و Kill Switch.")
    if policy.require_model_card:
        if not card.purpose.strip():
            errors.append("Model Card باید هدف (purpose) داشته باشد.")
        if not card.training_data.strip():
            errors.append("Model Card باید داده آموزش را مشخص کند.")
        if not card.feature_schema.strip():
            errors.append("Model Card باید schema ویژگی‌ها را مشخص کند.")
        if not card.limitations:
            errors.append("Model Card باید محدودیت‌ها را فهرست کند.")
    if card.tier >= 2 and not card.metrics:
        errors.append("برای Tier 2+ ثبت معیارهای OOS الزامی است.")
    if policy.require_calibration and card.provides_probability:
        if not card.calibration:
            errors.append("مدل احتمالی باید گزارش کالیبراسیون داشته باشد.")
        ece = card.calibration.get("ece")
        if ece is None or float(ece) < 0:
            errors.append("گزارش کالیبراسیون باید ECE غیرمنفی داشته باشد.")
    if card.valid_until is not None and card.valid_from is not None and card.valid_until <= card.valid_from:
        errors.append("valid_until باید بعد از valid_from باشد.")
    return errors


class ModelRegistryService:
    def __init__(
        self,
        repository,
        db: Database,
        audit,
        *,
        policy: GovernancePolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.db = db
        self.audit = audit
        self.policy = policy or GovernancePolicy()
        self.clock = clock or utcnow

    def register(self, card: ModelCard, *, actor: str) -> ModelCard:
        errors = validate_model_card(card, self.policy)
        if errors:
            raise ValidationError("؛ ".join(errors))
        record = ModelRecord(
            model_id=card.model_id,
            version=card.version,
            dataset_snapshot=card.dataset_snapshot,
            feature_schema=card.feature_schema,
            code_hash=card.code_hash,
            config_hash=card.config_hash,
            validation_report={"card": card.to_dict()},
            approved_by=card.approved_by,
            approved_at=card.approved_at,
            status=card.status,
        )
        self.repository.save(record)
        self.audit.append(
            AuditAction.MODEL_REGISTERED,
            "model",
            f"{card.model_id}@{card.version}",
            actor=actor,
            payload={"tier": card.tier, "status": card.status, "content_hash": card.content_hash()},
        )
        return card

    def get(self, model_id: str, version: str) -> ModelCard:
        for card in self.list():
            if card.model_id == model_id and card.version == version:
                return card
        from fxars.core.errors import NotFoundError

        raise NotFoundError(f"مدل یافت نشد: {model_id}@{version}")

    def list(self) -> list[ModelCard]:
        cards: list[ModelCard] = []
        for record in self.repository.list():
            payload = (record.validation_report or {}).get("card")
            if not payload:
                continue
            cards.append(_card_from_dict(payload))
        return cards

    def promote(
        self,
        model_id: str,
        version: str,
        target: str,
        *,
        actor: str,
        approved_by: str = "",
        reason: str = "",
        shadow_completed: bool | None = None,
        oos_passed: bool | None = None,
        independent_approval: bool | None = None,
        kill_switch_ready: bool | None = None,
    ) -> ModelCard:
        card = self.get(model_id, version)
        target = target.strip().upper()
        if target not in STATUSES:
            raise ValidationError(f"وضعیت مدل نامعتبر است: {target}")
        if target not in ALLOWED_TRANSITIONS.get(card.status, set()):
            raise ModelTransitionError(
                f"گذار مدل از {card.status} به {target} مجاز نیست.",
                details={"allowed": sorted(ALLOWED_TRANSITIONS.get(card.status, set()))},
            )
        if not reason.strip():
            raise ValidationError("تغییر وضعیت مدل نیازمند دلیل است.")
        updated = replace(
            card,
            status=target,
            shadow_completed=card.shadow_completed if shadow_completed is None else shadow_completed,
            oos_passed=card.oos_passed if oos_passed is None else oos_passed,
            independent_approval=(
                card.independent_approval if independent_approval is None else independent_approval
            ),
            kill_switch_ready=(
                card.kill_switch_ready if kill_switch_ready is None else kill_switch_ready
            ),
            approved_by=approved_by or card.approved_by,
            approved_at=self.clock() if target == "ACTIVE" else card.approved_at,
        )
        if target == "ACTIVE":
            errors = self._activation_errors(updated, actor=actor)
            if errors:
                raise ValidationError("؛ ".join(errors))
        errors = validate_model_card(updated, self.policy)
        if errors:
            raise ValidationError("؛ ".join(errors))
        self._save(updated)
        self.audit.append(
            AuditAction.MODEL_STATUS_CHANGED,
            "model",
            f"{model_id}@{version}",
            actor=actor,
            payload={
                "from": card.status,
                "to": target,
                "tier": updated.tier,
                "approved_by": updated.approved_by,
                "reason": reason,
            },
        )
        return updated

    def _activation_errors(self, card: ModelCard, *, actor: str) -> list[str]:
        policy = self.policy
        errors: list[str] = []
        if policy.require_shadow_before_active and not card.shadow_completed:
            errors.append("فعال‌سازی مدل نیازمند عبور از Shadow Mode است.")
        if card.tier >= 2 and policy.require_independent_approval_tier2:
            if not card.independent_approval:
                errors.append("Tier 2+ نیازمند تأیید مستقل است.")
            if not card.approved_by or card.approved_by == actor:
                errors.append("تأییدکننده باید مستقل از اپراتور فعال‌ساز باشد.")
        if card.tier >= 2 and not card.oos_passed:
            errors.append("Tier 2+ نیازمند نتیجه OOS است.")
        if card.tier >= 3 and not card.kill_switch_ready:
            errors.append("Tier 3 نیازمند آمادگی Kill Switch است.")
        if card.valid_until is not None and card.valid_until <= self.clock():
            errors.append("اعتبار Model Card منقضی شده است.")
        return errors

    def record_drift(
        self,
        model_id: str,
        *,
        drift_type: str,
        value: float,
        threshold: float,
        detected_at: datetime | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        moment = detected_at or self.clock()
        payload = {
            "model_id": model_id,
            "drift_type": drift_type,
            "value": float(value),
            "threshold": float(threshold),
            "exceeded": float(value) > float(threshold),
            "detected_at": format_ts(moment),
        }
        drift_id = "drift_" + sha256_obj(payload)[:24]
        self.db.execute(
            "INSERT OR REPLACE INTO model_drift (drift_id, model_id, detected_at, payload) "
            "VALUES (?, ?, ?, ?)",
            (drift_id, model_id, format_ts(moment), json.dumps(payload, ensure_ascii=False)),
        )
        self.audit.append(
            AuditAction.MODEL_DRIFT_RECORDED,
            "model",
            model_id,
            actor=actor,
            payload=payload,
        )
        return payload

    def _save(self, card: ModelCard) -> None:
        self.repository.save(
            ModelRecord(
                model_id=card.model_id,
                version=card.version,
                dataset_snapshot=card.dataset_snapshot,
                feature_schema=card.feature_schema,
                code_hash=card.code_hash,
                config_hash=card.config_hash,
                validation_report={"card": card.to_dict()},
                approved_by=card.approved_by,
                approved_at=card.approved_at,
                status=card.status,
            )
        )


def _card_from_dict(data: dict[str, Any]) -> ModelCard:
    return ModelCard(
        model_id=data["model_id"],
        version=data["version"],
        tier=int(data.get("tier", 0)),
        purpose=data.get("purpose", ""),
        owner=data.get("owner", ""),
        training_data=data.get("training_data", ""),
        feature_schema=data.get("feature_schema", ""),
        limitations=tuple(data.get("limitations", ())),
        metrics=data.get("metrics", {}),
        calibration=data.get("calibration", {}),
        provides_probability=bool(data.get("provides_probability", False)),
        dataset_snapshot=data.get("dataset_snapshot", ""),
        code_hash=data.get("code_hash", ""),
        config_hash=data.get("config_hash", ""),
        valid_from=parse_ts(data["valid_from"]) if data.get("valid_from") else None,
        valid_until=parse_ts(data["valid_until"]) if data.get("valid_until") else None,
        status=data.get("status", "DRAFT"),
        approved_by=data.get("approved_by"),
        approved_at=parse_ts(data["approved_at"]) if data.get("approved_at") else None,
        kill_switch_ready=bool(data.get("kill_switch_ready", False)),
        shadow_completed=bool(data.get("shadow_completed", False)),
        oos_passed=bool(data.get("oos_passed", False)),
        independent_approval=bool(data.get("independent_approval", False)),
    )
