"""Advisor: generate actionable recommendations from analysis + scenario + risk."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class AdviceAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT = "EXIT"
    STAY_OUT = "STAY_OUT"
    WAIT = "WAIT"


@dataclass
class Advice:
    symbol: str
    timeframe: str
    action: AdviceAction
    confidence: float  # 0.0 - 1.0
    reason: str
    suggestions: list[str] = field(default_factory=list)
    entry: Decimal | None = None
    stop: Decimal | None = None
    targets: list[Decimal] = field(default_factory=list)
    scenario_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "action": self.action.value,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "suggestions": self.suggestions,
            "entry": str(self.entry) if self.entry else None,
            "stop": str(self.stop) if self.stop else None,
            "targets": [str(t) for t in self.targets],
            "scenario_id": self.scenario_id,
            "timestamp": self.timestamp.isoformat(),
        }


def generate_advice(
    *,
    decision: Any,
    scenario: Any | None,
    symbol: str,
    timeframe: str,
    risk_decision: Any | None = None,
    instrument_spec: Any | None = None,
) -> Advice:
    """Convert Decision + Scenario + RiskDecision into actionable Advice."""

    action_val = decision.action.value if hasattr(decision.action, "value") else str(decision.action)
    score = float(decision.score)
    coverage = float(getattr(decision, "coverage", 0.0))
    stability = float(getattr(decision, "stability", 0.0))
    strength = float(getattr(decision, "strength", 0.0))
    no_trade_reason = getattr(decision, "no_trade_reason", None)

    # Extract scenario levels
    entry = stop = None
    targets: list[Decimal] = []
    scenario_id = None
    if scenario is not None:
        scenario_id = scenario.scenario_id
        try:
            entry_val = (scenario.entry_condition or {}).get("level")
            if entry_val:
                entry = Decimal(str(entry_val))
            stop_val = (scenario.stop_logic or {}).get("level")
            if stop_val:
                stop = Decimal(str(stop_val))
            for t in (scenario.target_logic or ()):
                p = t.get("price")
                if p:
                    targets.append(Decimal(str(p)))
        except Exception:
            pass

    # ---- NO TRADE cases ----
    if action_val == "NO_TRADE":
        if no_trade_reason == "DATA_STALE":
            return Advice(
                symbol=symbol, timeframe=timeframe, action=AdviceAction.WAIT,
                confidence=0.9,
                reason="داده بازار کهنه است؛ صبر کنید تا داده تازه برسد.",
                suggestions=[
                    "منبع داده یا اتصال MT5 را بررسی کنید.",
                    "تا بروزرسانی کندل بعدی صبر کنید.",
                ],
                scenario_id=scenario_id,
            )
        if no_trade_reason == "DATA_QUALITY_FAIL":
            return Advice(
                symbol=symbol, timeframe=timeframe, action=AdviceAction.STAY_OUT,
                confidence=0.85,
                reason="کیفیت داده در وضعیت FAIL است؛ ورود نکنید.",
                suggestions=[
                    "گزارش کیفیت داده را بررسی کنید.",
                    "منبع جایگزین (داده با کیفیت‌تر) انتخاب کنید.",
                ],
                scenario_id=scenario_id,
            )
        if no_trade_reason == "EVIDENCE_CONFLICT":
            return Advice(
                symbol=symbol, timeframe=timeframe, action=AdviceAction.WAIT,
                confidence=0.75,
                reason="تعارض در شواهد؛ سیگنال نامشخص است.",
                suggestions=[
                    "منتظر تاییدیه در تایم‌فریم بالاتر باشید.",
                    "تنها در صورت شکست ساختار واضح اقدام کنید.",
                ],
                scenario_id=scenario_id,
            )
        if no_trade_reason in ("INSUFFICIENT_EVIDENCE", "INSUFFICIENT_COVERAGE"):
            return Advice(
                symbol=symbol, timeframe=timeframe, action=AdviceAction.WAIT,
                confidence=0.6,
                reason="شواهد کافی برای تصمیم‌گیری وجود ندارد.",
                suggestions=[
                    "به تایم‌فریم بالاتر (مثلاً H4 یا D1) نگاه کنید.",
                    "منتظر کندل بسته جدید باشید.",
                ],
                scenario_id=scenario_id,
            )
        if no_trade_reason == "UNSTABLE_SIGNAL":
            return Advice(
                symbol=symbol, timeframe=timeframe, action=AdviceAction.WAIT,
                confidence=0.7,
                reason="سیگنال ناپایدار است؛ در کندل‌های اخیر تغییر جهت داشته.",
                suggestions=[
                    "منتظر تثبیت قیمت بالای/زیر سطح کلیدی باشید.",
                    "به تایم‌فریم بالاتر رجوع کنید.",
                ],
                scenario_id=scenario_id,
            )
        # fallback
        return Advice(
            symbol=symbol, timeframe=timeframe, action=AdviceAction.STAY_OUT,
            confidence=0.5,
            reason=f"بدون معامله: {no_trade_reason or 'UNKNOWN'}",
            scenario_id=scenario_id,
        )

    # ---- LONG / SHORT ----
    if scenario is None:
        return Advice(
            symbol=symbol, timeframe=timeframe, action=AdviceAction.WAIT,
            confidence=0.4,
            reason="سیگنال صادر شد اما سناریو ساخته نشد.",
            suggestions=["به داشبورد مراجعه کنید."],
        )

    # Confidence based on strength, coverage, stability
    confidence = min(1.0, 0.3 + 0.5 * strength + 0.2 * coverage)
    confidence = confidence * (0.7 + 0.3 * stability)
    confidence = round(max(0.0, min(1.0, confidence)), 3)

    # Risk gate check
    risk_approved = None
    if risk_decision is not None:
        risk_approved = bool(getattr(risk_decision, "approved", False))

    suggestions: list[str] = []

    if action_val == "LONG":
        action = AdviceAction.BUY
        reason = f"سیگنال صعودی (Score {score:+.3f}) با پوشش {coverage:.0%}."
    elif action_val == "SHORT":
        action = AdviceAction.SELL
        reason = f"سیگنال نزولی (Score {score:+.3f}) با پوشش {coverage:.0%}."
    else:
        action = AdviceAction.WAIT
        reason = "سیگنال نامشخص."

    # Risk gate specific advice
    if risk_approved is False and risk_decision is not None:
        failed = list(getattr(risk_decision, "checks_failed", ()) or ())
        action = AdviceAction.STAY_OUT
        confidence = min(confidence, 0.5)
        reason = f"سیگنال {action_val} اما Risk Gate رد کرد ({getattr(risk_decision, 'reason_code', 'UNKNOWN')})."
        if "KILL_SWITCH_ACTIVE" in failed:
            suggestions.append("Kill Switch فعال است؛ ابتدا آن را غیرفعال کنید.")
        if "SCENARIO_INVALID" in failed:
            suggestions.append("سناریو معتبر نیست (DRAFT است یا منقضی). ابتدا آن را فعال کنید.")
        if "SIGNAL_TOO_WEAK" in failed:
            suggestions.append("قدرت سیگنال کم است؛ منتظر شواهد بیشتر بمانید.")
        if "SPREAD_LIMIT" in failed:
            suggestions.append("اسپرد بالاست؛ در زمان اسپرد پایین‌تر اقدام کنید.")

    # Suggestions based on signal
    if action == AdviceAction.BUY:
        suggestions.append(f"ورود در {entry} با حد ضرر {stop}.")
        if targets:
            suggestions.append(f"هدف اول: {targets[0]}" + (f"، هدف دوم: {targets[1]}" if len(targets) > 1 else ""))
        suggestions.append("حجم را بر اساس ۰.۲۵٪ ریسک حساب تنظیم کنید.")
        if coverage < 0.5:
            suggestions.append("پوشش شواهد پایین است؛ با احتیاط عمل کنید.")
    elif action == AdviceAction.SELL:
        suggestions.append(f"ورود در {entry} با حد ضرر {stop}.")
        if targets:
            suggestions.append(f"هدف اول: {targets[0]}" + (f"، هدف دوم: {targets[1]}" if len(targets) > 1 else ""))
        suggestions.append("حجم را بر اساس ۰.۲۵٪ ریسک حساب تنظیم کنید.")
        if coverage < 0.5:
            suggestions.append("پوشش شواهد پایین است؛ با احتیاط عمل کنید.")

    # Scenario status check
    if scenario is not None:
        status = scenario.status.value if hasattr(scenario.status, "value") else str(scenario.status)
        if status == "DRAFT":
            suggestions.append("سناریو در وضعیت DRAFT است؛ ابتدا آن را ارزیابی کنید (evaluate).")
        elif status == "WATCH":
            suggestions.append("سناریو در وضعیت WATCH است؛ منتظر نزدیک شدن قیمت به Entry باشید.")
        elif status == "ARMED":
            suggestions.append("سناریو ARMED است؛ منتظر فعال شدن Trigger باشید.")
        elif status == "TRIGGERED":
            suggestions.append("Trigger فعال شده؛ سناریو آماده اجراست.")
        elif status in ("INVALIDATED", "EXPIRED"):
            suggestions.append(f"سناریو {status} است؛ دیگر معتبر نیست.")

    return Advice(
        symbol=symbol,
        timeframe=timeframe,
        action=action,
        confidence=confidence,
        reason=reason,
        suggestions=suggestions,
        entry=entry,
        stop=stop,
        targets=targets,
        scenario_id=scenario_id,
    )


def format_advice_text(advice: Advice) -> str:
    """Human-readable multi-line text (for console/telegram/desktop)."""
    emoji = {
        AdviceAction.BUY: "🟢", AdviceAction.SELL: "🔴",
        AdviceAction.HOLD: "🟡", AdviceAction.EXIT: "🟠",
        AdviceAction.STAY_OUT: "⚪", AdviceAction.WAIT: "🔵",
    }.get(advice.action, "⚪")

    lines = [
        f"{emoji} {advice.symbol} {advice.timeframe} — {advice.action.value}",
        f"اعتماد: {advice.confidence:.0%}",
        "",
        advice.reason,
    ]
    if advice.suggestions:
        lines.append("")
        lines.append("پیشنهادها:")
        for s in advice.suggestions:
            lines.append(f"  • {s}")
    return "\n".join(lines)
