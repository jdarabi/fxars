"""سیاست‌های تکمیلی تصمیم: اعتماد داده، بودجه عدم‌قطعیت و حاکمیت مدل.

مبنای این ماژول «سند تکمیلی ۱.۱» است:
- بخش ۴-۲: Data Trust Score
- بخش ۷-۱ و ۷-۲: امتیاز ترکیبی و تفکیک عدم‌قطعیت
- بخش ۶: Model Risk Tiering و دروازه انتشار
- بخش ۹-۲: معیارهای پذیرش عددی

این سیاست‌ها همراه `config_hash` در بازتولید نتایج ثبت می‌شوند؛ تغییر آستانه‌ها
باید نسخه‌دار و قابل ردیابی باشد.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


@dataclass(frozen=True)
class TrustPolicy:
    """آستانه‌های Data Trust Score (§۴-۲)."""

    min_score: float = 0.60
    freshness_max_age_bars: float = 2.0
    max_gap_bars: int = 3
    max_spread_jump_ratio: float = 3.0
    default_source_reliability: float = 1.0
    w_freshness: float = 0.30
    w_completeness: float = 0.20
    w_consistency: float = 0.20
    w_schema_validity: float = 0.15
    w_source_reliability: float = 0.15

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrustPolicy:
        data = _dict(data)
        base = cls()
        return cls(
            min_score=float(data.get("min_score", base.min_score)),
            freshness_max_age_bars=float(
                data.get("freshness_max_age_bars", base.freshness_max_age_bars)
            ),
            max_gap_bars=int(data.get("max_gap_bars", base.max_gap_bars)),
            max_spread_jump_ratio=float(
                data.get("max_spread_jump_ratio", base.max_spread_jump_ratio)
            ),
            default_source_reliability=float(
                data.get("default_source_reliability", base.default_source_reliability)
            ),
            w_freshness=float(data.get("w_freshness", base.w_freshness)),
            w_completeness=float(data.get("w_completeness", base.w_completeness)),
            w_consistency=float(data.get("w_consistency", base.w_consistency)),
            w_schema_validity=float(
                data.get("w_schema_validity", base.w_schema_validity)
            ),
            w_source_reliability=float(
                data.get("w_source_reliability", base.w_source_reliability)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        from fxars.core.serde import jsonable

        return jsonable(self)

    @property
    def weights(self) -> dict[str, float]:
        return {
            "freshness": self.w_freshness,
            "completeness": self.w_completeness,
            "consistency": self.w_consistency,
            "schema_validity": self.w_schema_validity,
            "source_reliability": self.w_source_reliability,
        }


@dataclass(frozen=True)
class UncertaintyPolicy:
    """آستانه‌ها و وزن‌های بودجه عدم‌قطعیت (§۷-۲)."""

    max_total: float = 0.60
    wait_threshold: float = 0.45
    w_data: float = 0.30
    w_model: float = 0.15
    w_regime: float = 0.20
    w_conflict: float = 0.20
    w_execution: float = 0.15
    model_uncertainty_none: float = 0.10
    model_uncertainty_uncalibrated: float = 0.50
    execution_cost_threshold: float = 0.25
    regime_uncertain_floor: float = 0.60

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UncertaintyPolicy:
        data = _dict(data)
        base = cls()
        return cls(
            max_total=float(data.get("max_total", base.max_total)),
            wait_threshold=float(data.get("wait_threshold", base.wait_threshold)),
            w_data=float(data.get("w_data", base.w_data)),
            w_model=float(data.get("w_model", base.w_model)),
            w_regime=float(data.get("w_regime", base.w_regime)),
            w_conflict=float(data.get("w_conflict", base.w_conflict)),
            w_execution=float(data.get("w_execution", base.w_execution)),
            model_uncertainty_none=float(
                data.get("model_uncertainty_none", base.model_uncertainty_none)
            ),
            model_uncertainty_uncalibrated=float(
                data.get("model_uncertainty_uncalibrated", base.model_uncertainty_uncalibrated)
            ),
            execution_cost_threshold=float(
                data.get("execution_cost_threshold", base.execution_cost_threshold)
            ),
            regime_uncertain_floor=float(
                data.get("regime_uncertain_floor", base.regime_uncertain_floor)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        from fxars.core.serde import jsonable

        return jsonable(self)

    @property
    def weights(self) -> dict[str, float]:
        return {
            "data": self.w_data,
            "model": self.w_model,
            "regime": self.w_regime,
            "conflict": self.w_conflict,
            "execution": self.w_execution,
        }


@dataclass(frozen=True)
class EvidencePolicy:
    """پارامترهای امتیاز ترکیبی شواهد (§۷-۱)."""

    conflict_penalty: float = 0.12
    reliability_floor: float = 0.25
    regime_fit_default: float = 1.0
    redundant_gap_bars: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidencePolicy:
        data = _dict(data)
        base = cls()
        return cls(
            conflict_penalty=float(data.get("conflict_penalty", base.conflict_penalty)),
            reliability_floor=float(data.get("reliability_floor", base.reliability_floor)),
            regime_fit_default=float(
                data.get("regime_fit_default", base.regime_fit_default)
            ),
            redundant_gap_bars=int(data.get("redundant_gap_bars", base.redundant_gap_bars)),
        )

    def to_dict(self) -> dict[str, Any]:
        from fxars.core.serde import jsonable

        return jsonable(self)


@dataclass(frozen=True)
class GovernancePolicy:
    """دروازه انتشار مدل و سیاست (§۶ و §۱۲-۲)."""

    mvp_tier3_forbidden: bool = True
    require_independent_approval_tier2: bool = True
    require_calibration: bool = True
    require_shadow_before_active: bool = True
    require_model_card: bool = True
    max_active_models_per_scope: int = 3

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GovernancePolicy:
        data = _dict(data)
        base = cls()
        return cls(
            mvp_tier3_forbidden=bool(
                data.get("mvp_tier3_forbidden", base.mvp_tier3_forbidden)
            ),
            require_independent_approval_tier2=bool(
                data.get(
                    "require_independent_approval_tier2",
                    base.require_independent_approval_tier2,
                )
            ),
            require_calibration=bool(
                data.get("require_calibration", base.require_calibration)
            ),
            require_shadow_before_active=bool(
                data.get("require_shadow_before_active", base.require_shadow_before_active)
            ),
            require_model_card=bool(
                data.get("require_model_card", base.require_model_card)
            ),
            max_active_models_per_scope=int(
                data.get("max_active_models_per_scope", base.max_active_models_per_scope)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        from fxars.core.serde import jsonable

        return jsonable(self)


@dataclass(frozen=True)
class AcceptancePolicy:
    """معیارهای پذیرش پژوهش (§۹-۲)؛ اعداد پیشنهادی و قابل تغییرند."""

    min_oos_trades: int = 200
    min_profit_factor: float = 1.2
    max_drawdown: float = 0.15
    max_ece: float = 0.05
    min_calmar: float = 0.0
    require_positive_sharpe: bool = True
    max_train_test_gap: float = 0.50

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AcceptancePolicy:
        data = _dict(data)
        base = cls()
        return cls(
            min_oos_trades=int(data.get("min_oos_trades", base.min_oos_trades)),
            min_profit_factor=float(data.get("min_profit_factor", base.min_profit_factor)),
            max_drawdown=float(data.get("max_drawdown", base.max_drawdown)),
            max_ece=float(data.get("max_ece", base.max_ece)),
            min_calmar=float(data.get("min_calmar", base.min_calmar)),
            require_positive_sharpe=bool(
                data.get("require_positive_sharpe", base.require_positive_sharpe)
            ),
            max_train_test_gap=float(
                data.get("max_train_test_gap", base.max_train_test_gap)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        from fxars.core.serde import jsonable

        return jsonable(self)


@dataclass(frozen=True)
class DecisionPolicy:
    """بسته سیاست تکمیلی تصمیم؛ یک شیء برای config_hash و بازتولید."""

    trust: TrustPolicy = field(default_factory=TrustPolicy)
    uncertainty: UncertaintyPolicy = field(default_factory=UncertaintyPolicy)
    evidence: EvidencePolicy = field(default_factory=EvidencePolicy)
    governance: GovernancePolicy = field(default_factory=GovernancePolicy)
    acceptance: AcceptancePolicy = field(default_factory=AcceptancePolicy)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionPolicy:
        data = _dict(data)
        return cls(
            trust=TrustPolicy.from_dict(data.get("trust", {})),
            uncertainty=UncertaintyPolicy.from_dict(data.get("uncertainty", {})),
            evidence=EvidencePolicy.from_dict(data.get("evidence", {})),
            governance=GovernancePolicy.from_dict(data.get("governance", {})),
            acceptance=AcceptancePolicy.from_dict(data.get("acceptance", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trust": self.trust.to_dict(),
            "uncertainty": self.uncertainty.to_dict(),
            "evidence": self.evidence.to_dict(),
            "governance": self.governance.to_dict(),
            "acceptance": self.acceptance.to_dict(),
        }

    def problems(self) -> list[str]:
        problems: list[str] = []
        trust = self.trust
        if not 0.0 < trust.min_score < 1.0:
            problems.append(
                f"decision.trust.min_score ({trust.min_score}) باید در بازه (0, 1) باشد."
            )
        total_weight = sum(trust.weights.values())
        if abs(total_weight - 1.0) > 0.01:
            problems.append(
                f"مجموع وزن‌های decision.trust ({total_weight:.3f}) باید ۱ باشد."
            )
        uncertainty = self.uncertainty
        if not 0.0 <= uncertainty.wait_threshold < uncertainty.max_total <= 1.0:
            problems.append(
                "ترتیب آستانه‌های عدم‌قطعیت نامعتبر است: "
                f"wait_threshold ({uncertainty.wait_threshold}) < max_total ({uncertainty.max_total}) ≤ 1."
            )
        total_weight = sum(uncertainty.weights.values())
        if abs(total_weight - 1.0) > 0.01:
            problems.append(
                f"مجموع وزن‌های decision.uncertainty ({total_weight:.3f}) باید ۱ باشد."
            )
        if not 0.0 <= self.evidence.conflict_penalty <= 1.0:
            problems.append("decision.evidence.conflict_penalty باید در بازه [0, 1] باشد.")
        acceptance = self.acceptance
        if acceptance.min_oos_trades < 1:
            problems.append("decision.acceptance.min_oos_trades باید مثبت باشد.")
        if not 0.0 < acceptance.max_drawdown < 1.0:
            problems.append("decision.acceptance.max_drawdown باید در بازه (0, 1) باشد.")
        if acceptance.min_profit_factor <= 0:
            problems.append("decision.acceptance.min_profit_factor باید مثبت باشد.")
        return problems
