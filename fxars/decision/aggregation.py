"""تجمیع شواهد با کنترل هم‌بستگی خانواده‌ها و صدور تصمیم قابل توضیح.

جمع ساده امتیازها ممنوع است: هر خانواده (ساختار، روند، مومنتوم، سطوح، حجم، بنیادی،
بین‌بازاری) سقف سهم دارد و تعارض/پوشش/پایداری کنترل می‌شود.
"""

from __future__ import annotations

from datetime import datetime

from fxars.config.settings import AnalysisSettings
from fxars.core.numerics import clamp
from fxars.domain.enums import DecisionAction, Direction, EvidenceFamily, Timeframe
from fxars.domain.models import Decision, Evidence

FAMILY_WEIGHTS: dict[EvidenceFamily, float] = {
    EvidenceFamily.STRUCTURE: 1.0,
    EvidenceFamily.TREND: 0.9,
    EvidenceFamily.MOMENTUM: 0.8,
    EvidenceFamily.LEVELS: 0.7,
    EvidenceFamily.VOLUME: 0.5,
    EvidenceFamily.FUNDAMENTAL: 0.85,
    EvidenceFamily.INTERMARKET: 0.7,
    EvidenceFamily.VOLATILITY: 0.0,
}

DIRECTIONAL_FAMILIES: tuple[EvidenceFamily, ...] = (
    EvidenceFamily.STRUCTURE,
    EvidenceFamily.TREND,
    EvidenceFamily.MOMENTUM,
    EvidenceFamily.LEVELS,
    EvidenceFamily.VOLUME,
    EvidenceFamily.FUNDAMENTAL,
    EvidenceFamily.INTERMARKET,
)

# تعارض فقط در خانواده‌های «جهت‌دهنده اصلی» سنجیده می‌شود؛ سطوح/حجم/نوسان زمینه‌ای‌اند
CONFLICT_FAMILIES: frozenset[EvidenceFamily] = frozenset({
    EvidenceFamily.STRUCTURE,
    EvidenceFamily.TREND,
    EvidenceFamily.MOMENTUM,
    EvidenceFamily.FUNDAMENTAL,
    EvidenceFamily.INTERMARKET,
})


def filter_usable(
    evidences: list[Evidence],
    *,
    as_of: datetime,
    timeframe: str,
    settings: AnalysisSettings,
    age_bars: float | None = None,
) -> list[Evidence]:
    tf = Timeframe.parse(timeframe)
    horizon = tf.delta * (age_bars if age_bars is not None else settings.max_evidence_age_bars)
    return [
        evidence
        for evidence in evidences
        if evidence.available_at <= as_of
        and evidence.available_at >= as_of - horizon
        and evidence.strength >= settings.min_strength
        and (evidence.expiry is None or evidence.expiry > as_of)
    ]


def family_scores(evidences: list[Evidence], settings: AnalysisSettings, weights: dict[EvidenceFamily, float] | None = None) -> dict[EvidenceFamily, float]:
    weights = weights or FAMILY_WEIGHTS
    scores: dict[EvidenceFamily, float] = {}
    for family in EvidenceFamily:
        items = [evidence for evidence in evidences if evidence.family is family]
        if not items:
            continue
        long_max = max((float(item.strength) for item in items if item.direction is Direction.LONG), default=0.0)
        short_max = max((float(item.strength) for item in items if item.direction is Direction.SHORT), default=0.0)
        cap = settings.family_cap * weights.get(family, 0.5)
        scores[family] = clamp((long_max - short_max) * cap, -cap, cap)
    return scores


def _net(scores: dict[EvidenceFamily, float]) -> float:
    return sum(scores.values())


def aggregate_evidence(
    evidences: list[Evidence],
    settings: AnalysisSettings,
    *,
    as_of: datetime,
    timeframe: str,
) -> Decision:
    Timeframe.parse(timeframe)
    usable = filter_usable(evidences, as_of=as_of, timeframe=timeframe, settings=settings)
    if not usable:
        return Decision(
            action=DecisionAction.NO_TRADE,
            direction=Direction.NEUTRAL,
            score=0.0,
            confidence_raw=0.0,
            family_scores={},
            conflicts=(),
            coverage=0.0,
            stability=0.0,
            reasons=("هیچ شاهد تازه و معتبری در پنجره تصمیم وجود ندارد.",),
            evidence_ids=(),
            no_trade_reason="NO_USABLE_EVIDENCE",
        )

    scores = family_scores(usable, settings)
    score = _net(scores)

    by_family: dict[EvidenceFamily, dict[str, float]] = {}
    for evidence in usable:
        entry = by_family.setdefault(evidence.family, {"long": 0.0, "short": 0.0})
        key = "long" if evidence.direction is Direction.LONG else "short" if evidence.direction is Direction.SHORT else "neutral"
        if key in entry:
            entry[key] = max(entry[key], float(evidence.strength))
    conflicts = tuple(
        family.value
        for family, values in by_family.items()
        if family in CONFLICT_FAMILIES
        and values["long"] >= settings.conflict_threshold and values["short"] >= settings.conflict_threshold
    )

    covered = {evidence.family for evidence in usable if evidence.family in DIRECTIONAL_FAMILIES and evidence.direction is not Direction.NEUTRAL}
    coverage = len(covered) / len(DIRECTIONAL_FAMILIES)

    sign = 1 if score > 0 else -1 if score < 0 else 0
    stability = _stability(evidences, settings, as_of=as_of, timeframe=timeframe, sign=sign)

    reasons = [f"سهم خانواده‌ها: {_format_scores(scores)}"]
    if conflicts:
        reasons.append("تعارض شواهد در خانواده‌های: " + "، ".join(conflicts))
    top = sorted(usable, key=lambda item: float(item.strength), reverse=True)[:3]
    for evidence in top:
        reasons.append(f"{evidence.module_id}: {evidence.explanation}")

    base = dict(
        score=round(score, 4),
        confidence_raw=round(clamp(abs(score) * coverage * max(stability, 0.0), 0.0, 1.0), 4),
        family_scores={family.value: round(value, 4) for family, value in scores.items()},
        conflicts=conflicts,
        coverage=round(coverage, 4),
        stability=round(stability, 4),
        reasons=tuple(reasons),
        evidence_ids=tuple(evidence.evidence_id for evidence in sorted(usable, key=lambda item: float(item.strength), reverse=True)[:20]),
        strength=round(clamp(abs(score) / max(settings.family_cap * 2.5, 1e-9), 0.0, 1.0), 4),
    )

    if len(conflicts) > settings.max_conflict_families:
        return Decision(action=DecisionAction.NO_TRADE, direction=Direction.NEUTRAL, no_trade_reason="EVIDENCE_CONFLICT", **base)
    if coverage < settings.min_coverage:
        return Decision(action=DecisionAction.NO_TRADE, direction=Direction.NEUTRAL, no_trade_reason="INSUFFICIENT_COVERAGE", **base)
    if stability < settings.stability_min_agreement:
        return Decision(action=DecisionAction.NO_TRADE, direction=Direction.NEUTRAL, no_trade_reason="UNSTABLE_SIGNAL", **base)
    if abs(score) < settings.min_net_score:
        return Decision(action=DecisionAction.NO_TRADE, direction=Direction.NEUTRAL, no_trade_reason="INSUFFICIENT_EVIDENCE", **base)

    direction = Direction.LONG if score > 0 else Direction.SHORT
    action = DecisionAction.LONG if direction is Direction.LONG else DecisionAction.SHORT
    return Decision(action=action, direction=direction, **base)


def _stability(evidences: list[Evidence], settings: AnalysisSettings, *, as_of: datetime,
               timeframe: str, sign: int) -> float:
    if sign == 0:
        return 0.0
    tf = Timeframe.parse(timeframe)
    signs: list[int] = []
    for offset in (0, 1, 2):
        checkpoint = as_of - tf.delta * offset
        usable = filter_usable(evidences, as_of=checkpoint, timeframe=timeframe, settings=settings,
                               age_bars=settings.max_evidence_age_bars * 3)
        value = _net(family_scores(usable, settings))
        if abs(value) >= settings.min_net_score:
            signs.append(1 if value > 0 else -1)
    if len(signs) < 2:
        return 1.0
    return sum(1 for item in signs if item == sign) / len(signs)


def _format_scores(scores: dict[EvidenceFamily, float]) -> str:
    parts = [f"{family.value}={value:+.3f}" for family, value in sorted(scores.items(), key=lambda pair: abs(pair[1]), reverse=True)]
    return "، ".join(parts) if parts else "بدون شاهد"
