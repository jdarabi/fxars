"""هارنس Forward Test برای فاز ۶ (دمو).

تحلیل را به‌صورت event-time روی کندل‌های واقعی بازپخش می‌کند: در هر گام فقط
داده‌هایی که تا `available_at` همان کندل منتشر شده‌اند در دسترس تحلیل‌اند.
گزارش، توزیع تصمیم‌ها، سناریوهای ساخته‌شده و هرگونه نقض look-ahead را ثبت
می‌کند تا «forward test موفق» قابل اندازه‌گیری باشد.

نکته: هر تحلیل در پایگاه داده پلتفرم ثبت می‌شود؛ برای اجرای روی داده واقعی
از یک کپی/دیتابیس مستقل forward-test استفاده کنید، نه دیتابیس عملیاتی.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fxars.core.timeutil import ensure_utc, format_ts
from fxars.domain.enums import DecisionAction

DEFAULT_WARMUP = 300
MAX_RECORDED_STEPS = 5000


@dataclass(frozen=True)
class ForwardTestStep:
    index: int
    as_of: datetime
    status: str
    action: str
    direction: str
    confidence: float
    scenario_id: str | None
    scenario_status: str | None
    no_trade_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "as_of": format_ts(self.as_of),
            "status": self.status,
            "action": self.action,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "scenario_id": self.scenario_id,
            "scenario_status": self.scenario_status,
            "no_trade_reason": self.no_trade_reason,
        }


@dataclass
class ForwardTestReport:
    instrument_id: str
    timeframe: str
    start: datetime | None
    end: datetime | None
    warmup: int
    step_size: int
    steps: list[ForwardTestStep] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    lookahead_violations: list[str] = field(default_factory=list)

    def _count(self, action: str) -> int:
        return sum(1 for step in self.steps if step.action == action)

    @property
    def verdict(self) -> str:
        if self.errors:
            return "FAIL"
        if self.lookahead_violations:
            return "FAIL"
        if not self.steps:
            return "INSUFFICIENT_DATA"
        return "PASS"

    def to_dict(self) -> dict[str, Any]:
        scenario_counts: dict[str, int] = {}
        for step in self.steps:
            if step.scenario_status:
                scenario_counts[step.scenario_status] = scenario_counts.get(step.scenario_status, 0) + 1
        return {
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "start": format_ts(self.start) if self.start else None,
            "end": format_ts(self.end) if self.end else None,
            "warmup": self.warmup,
            "step_size": self.step_size,
            "candles_tested": len(self.steps),
            "long": self._count(DecisionAction.LONG.value),
            "short": self._count(DecisionAction.SHORT.value),
            "no_trade": self._count(DecisionAction.NO_TRADE.value),
            "scenarios": scenario_counts,
            "errors": self.errors,
            "lookahead_violations": self.lookahead_violations,
            "verdict": self.verdict,
            "steps": [step.to_dict() for step in self.steps[:MAX_RECORDED_STEPS]],
        }


class ForwardTestHarness:
    def __init__(
        self,
        platform: Any,
        instrument_id: str,
        timeframe: str,
        *,
        warmup: int = DEFAULT_WARMUP,
        step_size: int = 1,
        tenant_id: str = "default",
    ) -> None:
        if warmup < 1:
            raise ValueError("warmup باید حداقل ۱ باشد.")
        if step_size < 1:
            raise ValueError("step_size باید حداقل ۱ باشد.")
        self.platform = platform
        self.instrument_id = instrument_id
        self.timeframe = timeframe.upper()
        self.warmup = warmup
        self.step_size = step_size
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    def run(
        self,
        *,
        as_of: datetime | None = None,
        starts_at: datetime | None = None,
        actor: str = "forward_test",
        max_steps: int | None = None,
    ) -> ForwardTestReport:
        if max_steps is not None and max_steps < 1:
            raise ValueError("max_steps باید حداقل ۱ باشد.")
        moment = ensure_utc(as_of or self.platform.clock())
        source = self.platform.instruments.primary_source(self.instrument_id, self.timeframe)
        candles = self.platform.candles.range(
            self.instrument_id, self.timeframe, source_id=source,
            as_of=moment, closed_only=True,
        )
        if starts_at is not None:
            start = ensure_utc(starts_at)
            candles = [candle for candle in candles if candle.available_at >= start]
        report = ForwardTestReport(
            instrument_id=self.instrument_id,
            timeframe=self.timeframe,
            start=candles[self.warmup].available_at if len(candles) > self.warmup else None,
            end=candles[-1].available_at if len(candles) > self.warmup else None,
            warmup=self.warmup,
            step_size=self.step_size,
        )
        if len(candles) <= self.warmup:
            return report

        for index in range(self.warmup, len(candles), self.step_size):
            candle = candles[index]
            as_of_candle = candle.available_at
            try:
                result = self.platform.run_analysis(
                    self.instrument_id, self.timeframe, as_of=as_of_candle, actor=actor,
                    tenant_id=self.tenant_id,
                )
            except Exception as exc:  # noqa: BLE001 - گزارش خطا بخشی از خروجی است
                report.errors.append(f"{format_ts(as_of_candle)}: {exc}")
                if len(report.errors) >= 5:
                    break
                continue

            violations = self._lookahead(result, as_of_candle)
            report.lookahead_violations.extend(violations)
            decision = result.decision
            scenario = result.scenario
            report.steps.append(ForwardTestStep(
                index=index,
                as_of=as_of_candle,
                status=result.run.status.value,
                action=decision.action.value,
                direction=decision.direction.value,
                confidence=float(decision.confidence_raw),
                scenario_id=scenario.scenario_id if scenario else None,
                scenario_status=scenario.status.value if scenario else None,
                no_trade_reason=decision.no_trade_reason,
            ))
            if max_steps is not None and len(report.steps) >= max_steps:
                break
        return report

    # ------------------------------------------------------------------
    @staticmethod
    def _lookahead(result: Any, as_of: datetime) -> list[str]:
        violations: list[str] = []
        outcome = result.outcome
        if outcome is not None:
            for candle in outcome.candles:
                if candle.available_at > as_of:
                    violations.append(
                        f"{format_ts(as_of)}: candle available_at {format_ts(candle.available_at)}"
                    )
                    break
        for evidence in result.evidences:
            if evidence.available_at > as_of:
                violations.append(
                    f"{format_ts(as_of)}: evidence {evidence.evidence_id} available_at "
                    f"{format_ts(evidence.available_at)}"
                )
                break
        return violations


__all__ = [
    "ForwardTestHarness",
    "ForwardTestReport",
    "ForwardTestStep",
    "DEFAULT_WARMUP",
]
