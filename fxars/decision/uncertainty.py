"""بودجه عدم‌قطعیت — بخش ۷-۲ سند تکمیلی ۱.۱.

    U = α·U_data + β·U_model + γ·U_regime + δ·U_conflict + ε·U_execution

قاعده: اگر U > U_max باشد، خروجی حداقل WAIT است؛ در ریسک اجرایی بالا
(اسپرد/هزینه) خروجی NO_TRADE است. سامانه فعلی اقدام WAIT ندارد، بنابراین
سطوح HIGH و CRITICAL به NO_TRADE با دلیل ``UNCERTAINTY_TOO_HIGH`` نگاشت
می‌شوند تا اصل Fail-Safe حفظ شود.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fxars.config.decision import UncertaintyPolicy
from fxars.core.numerics import clamp


@dataclass(frozen=True)
class UncertaintyBreakdown:
    data: float
    model: float
    regime: float
    conflict: float
    execution: float
    total: float
    level: str
    max_total: float
    wait_threshold: float
    reasons: tuple[str, ...] = ()

    @property
    def requires_no_trade(self) -> bool:
        return self.level in {"HIGH", "CRITICAL"}

    @property
    def requires_wait(self) -> bool:
        return self.level in {"MEDIUM", "HIGH", "CRITICAL"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "components": {
                "data": round(self.data, 4),
                "model": round(self.model, 4),
                "regime": round(self.regime, 4),
                "conflict": round(self.conflict, 4),
                "execution": round(self.execution, 4),
            },
            "total": round(self.total, 4),
            "level": self.level,
            "max_total": self.max_total,
            "wait_threshold": self.wait_threshold,
            "requires_no_trade": self.requires_no_trade,
            "requires_wait": self.requires_wait,
            "reasons": list(self.reasons),
            "formula": "U = αU_data + βU_model + γU_regime + δU_conflict + εU_execution",
        }


def compute_uncertainty(
    *,
    data_trust: float,
    model_status: str = "none",
    regime_stability: float = 1.0,
    regime_uncertain: bool = False,
    conflict_families: int = 0,
    max_conflict_families: int = 1,
    spread_ok: bool = True,
    execution_cost_ratio: float = 0.0,
    policy: UncertaintyPolicy | None = None,
) -> UncertaintyBreakdown:
    policy = policy or UncertaintyPolicy()
    reasons: list[str] = []

    data_component = clamp(1.0 - float(data_trust), 0.0, 1.0)
    if data_component >= 0.4:
        reasons.append("اعتماد داده پایین است؛ بخش زیادی از بودجه عدم‌قطعیت مصرف شد.")

    normalized_model = str(model_status or "none").lower()
    if normalized_model == "calibrated":
        model_component = 0.0
    elif normalized_model == "uncalibrated":
        model_component = policy.model_uncertainty_uncalibrated
        reasons.append("مدل کالیبره نشده در مسیر تصمیم حاضر است.")
    else:
        model_component = policy.model_uncertainty_none
    model_component = clamp(model_component, 0.0, 1.0)

    stability = clamp(float(regime_stability), 0.0, 1.0)
    regime_component = clamp(1.0 - stability, 0.0, 1.0)
    if regime_uncertain:
        regime_component = max(regime_component, policy.regime_uncertain_floor)
        reasons.append("رژیم بازار نامشخص یا کم‌پایداری است.")
    elif regime_component >= 0.4:
        reasons.append("پایداری رژیم بازار پایین است.")

    conflict_component = clamp(
        float(conflict_families) / max(1, int(max_conflict_families)), 0.0, 1.0
    )
    if conflict_component > 0:
        reasons.append(f"تعارض شواهد در {conflict_families} خانواده دیده می‌شود.")

    if not spread_ok:
        execution_component = 1.0
        reasons.append("اسپرد از سقف مجاز بیشتر است؛ ریسک اجرا بالا است.")
    elif execution_cost_ratio > 0:
        execution_component = clamp(
            float(execution_cost_ratio) / max(policy.execution_cost_threshold, 1e-9),
            0.0,
            1.0,
        )
        if execution_component >= 0.5:
            reasons.append("هزینه اجرا نسبت به ریسک معامله بالاست.")
    else:
        execution_component = 0.0

    total = clamp(
        policy.w_data * data_component
        + policy.w_model * model_component
        + policy.w_regime * regime_component
        + policy.w_conflict * conflict_component
        + policy.w_execution * execution_component,
        0.0,
        1.0,
    )
    if total > policy.max_total:
        level = "CRITICAL"
        reasons.append(
            f"عدم‌قطعیت کل ({total:.0%}) از سقف ({policy.max_total:.0%}) بیشتر است."
        )
    elif total > policy.wait_threshold:
        level = "HIGH"
    elif total > policy.wait_threshold * 0.6:
        level = "MEDIUM"
    else:
        level = "LOW"

    return UncertaintyBreakdown(
        data=data_component,
        model=model_component,
        regime=regime_component,
        conflict=conflict_component,
        execution=execution_component,
        total=total,
        level=level,
        max_total=policy.max_total,
        wait_threshold=policy.wait_threshold,
        reasons=tuple(reasons),
    )
