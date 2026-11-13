"""امتیاز ترکیبی شواهد — بخش ۷-۱ سند تکمیلی ۱.۱.

    S = Σ w_i · E_i · R_i · F_i − P_conflict

- E_i: شاهد نرمال‌شده (قدرت خالص جهت‌دار در هر خانواده)
- R_i: قابلیت اعتماد شاهد (میانگین confidence_raw خانواده)
- F_i: سازگاری با رژیم بازار
- P_conflict: جریمه تعارض شواهد

وزن‌های خانواده از `analysis.FAMILY_WEIGHTS` می‌آیند و آستانه‌ها پیش از آزمون
نهایی در سیاست تصمیم تثبیت می‌شوند.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from fxars.config.decision import EvidencePolicy
from fxars.core.numerics import clamp
from fxars.decision.aggregation import CONFLICT_FAMILIES, FAMILY_WEIGHTS
from fxars.domain.enums import Direction, EvidenceFamily
from fxars.domain.models import Decision, Evidence


@dataclass(frozen=True)
class ScoreContribution:
    family: str
    evidence: float
    reliability: float
    regime_fit: float
    weight: float
    contribution: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "evidence": round(self.evidence, 4),
            "reliability": round(self.reliability, 4),
            "regime_fit": round(self.regime_fit, 4),
            "weight": round(self.weight, 4),
            "contribution": round(self.contribution, 4),
        }


@dataclass(frozen=True)
class CompositeScore:
    total: float
    conflict_penalty: float
    contributions: tuple[ScoreContribution, ...]
    conflict_families: tuple[str, ...] = ()
    formula: str = "S = Σ w·E·R·F − P_conflict"

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 4),
            "conflict_penalty": round(self.conflict_penalty, 4),
            "conflict_families": list(self.conflict_families),
            "formula": self.formula,
            "contributions": [item.to_dict() for item in self.contributions],
        }


def _family_net(evidences: list[Evidence]) -> tuple[float, float, bool]:
    long_max = max(
        (float(item.strength) for item in evidences if item.direction is Direction.LONG),
        default=0.0,
    )
    short_max = max(
        (float(item.strength) for item in evidences if item.direction is Direction.SHORT),
        default=0.0,
    )
    directional = [
        item
        for item in evidences
        if item.direction in (Direction.LONG, Direction.SHORT)
    ]
    reliability = (
        sum(float(item.confidence_raw) for item in directional) / len(directional)
        if directional
        else 0.0
    )
    return long_max - short_max, reliability, long_max > 0 and short_max > 0


def composite_score(
    evidences: Iterable[Evidence],
    *,
    decision: Decision | None = None,
    regime_fit: dict[str, float] | None = None,
    policy: EvidencePolicy | None = None,
) -> CompositeScore:
    policy = policy or EvidencePolicy()
    items = list(evidences)
    by_family: dict[EvidenceFamily, list[Evidence]] = {}
    for evidence in items:
        by_family.setdefault(evidence.family, []).append(evidence)

    contributions: list[ScoreContribution] = []
    conflict_families: list[str] = []
    penalty = 0.0
    for family in EvidenceFamily:
        family_items = by_family.get(family, [])
        if not family_items:
            continue
        net, reliability, has_conflict = _family_net(family_items)
        weight = float(FAMILY_WEIGHTS.get(family, 0.0))
        fit = float((regime_fit or {}).get(family.value, policy.regime_fit_default))
        contribution = weight * clamp(net, -1.0, 1.0) * clamp(
            reliability, policy.reliability_floor, 1.0
        ) * clamp(fit, 0.0, 1.0)
        contributions.append(
            ScoreContribution(
                family=family.value,
                evidence=net,
                reliability=reliability,
                regime_fit=fit,
                weight=weight,
                contribution=contribution,
            )
        )
        if has_conflict and family in CONFLICT_FAMILIES:
            conflict_families.append(family.value)
            penalty += policy.conflict_penalty

    total = sum(item.contribution for item in contributions) - penalty
    # اگر تصمیم نهایی NO_TRADE است، امتیاز ترکیبی نیز خنثی گزارش می‌شود.
    if decision is not None and decision.action.value == "NO_TRADE":
        total = min(total, 0.0)
    return CompositeScore(
        total=clamp(total, -1.0, 1.0),
        conflict_penalty=clamp(penalty, 0.0, 1.0),
        contributions=tuple(contributions),
        conflict_families=tuple(conflict_families),
    )
