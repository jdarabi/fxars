"""دروازه پذیرش پژوهش و تشخیص الگوهای ضدّی — بخش ۹-۲ و ۹-۳ سند تکمیلی ۱.۱.

هیچ نتیجه بک‌تستی «قابل انتشار» نیست مگر این دروازه را عبور کند. معیارها
عددی و از `AcceptancePolicy` می‌آیند تا تغییر آن‌ها نسخه‌دار و قابل ردیابی باشد.

اصطلاحات:
- OOS: خارج از نمونه (Locked Test / Walk-forward test).
- Anti-pattern: نشانه‌های رایج نتایج غیرقابل اعتماد (نمونه کوچک، نبود OOS،
  نادیده‌گرفتن هزینه‌ها، تک‌رژیمی بودن، وابستگی به یک دوره).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fxars.config.decision import AcceptancePolicy


@dataclass(frozen=True)
class AcceptanceCheck:
    code: str
    passed: bool
    detail: str
    value: Any = None
    limit: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "passed": self.passed,
            "detail": self.detail,
            "value": self.value,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class AntiPattern:
    code: str
    severity: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "detail": self.detail}


@dataclass(frozen=True)
class AcceptanceReport:
    passed: bool
    checks: tuple[AcceptanceCheck, ...]
    anti_patterns: tuple[AntiPattern, ...]
    thresholds: dict[str, Any] = field(default_factory=dict)

    @property
    def failures(self) -> tuple[AcceptanceCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
            "failures": [check.to_dict() for check in self.failures],
            "anti_patterns": [item.to_dict() for item in self.anti_patterns],
            "thresholds": self.thresholds,
        }


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _check(code: str, passed: bool, detail: str, value: Any = None,
           limit: Any = None) -> AcceptanceCheck:
    return AcceptanceCheck(code=code, passed=bool(passed), detail=detail, value=value, limit=limit)


def evaluate_acceptance(
    metrics: Mapping[str, Any],
    *,
    policy: AcceptancePolicy | None = None,
    train_metrics: Mapping[str, Any] | None = None,
    test_metrics: Mapping[str, Any] | None = None,
    calibration: Mapping[str, Any] | None = None,
    regime_breakdown: Mapping[str, Any] | None = None,
    has_locked_test: bool = False,
    has_walkforward: bool = False,
    is_oos: bool = True,
) -> AcceptanceReport:
    """ارزیابی عددی پذیرش و ثبت الگوهای ضدّی.

    `metrics` باید معیارهای بخش OOS باشد. اگر `is_oos=False` باشد، دروازه
    به‌صورت خودکار رد می‌شود (هیچ نتیجه درون‌نمونه‌ای قابل پذیرش نیست).
    """
    policy = policy or AcceptancePolicy()
    checks: list[AcceptanceCheck] = []
    anti: list[AntiPattern] = []

    trade_count = int(_num(metrics.get("trade_count"), 0) or 0)
    checks.append(_check(
        "OOS_SAMPLE",
        is_oos and trade_count >= policy.min_oos_trades,
        (
            f"تعداد معاملات OOS {trade_count} است و حداقل {policy.min_oos_trades} لازم است."
            if is_oos else "نتیجه از بخش خارج از نمونه (OOS) نیست."
        ),
        trade_count,
        policy.min_oos_trades,
    ))
    if trade_count < policy.min_oos_trades:
        anti.append(AntiPattern(
            "TINY_SAMPLE",
            "HIGH",
            f"نمونه {trade_count} معامله‌ای برای استنتاج آماری کافی نیست.",
        ))

    profit_factor = _num(metrics.get("profit_factor"))
    pf_ok = profit_factor is not None and profit_factor >= policy.min_profit_factor
    checks.append(_check(
        "PROFIT_FACTOR",
        pf_ok,
        (
            f"Profit Factor {profit_factor:.3f} کمتر از حداقل {policy.min_profit_factor} است."
            if profit_factor is not None and not pf_ok else
            "Profit Factor تعریف‌نشده است (زیان ناخالص صفر یا معامله‌ای ثبت نشده)."
            if profit_factor is None else
            f"Profit Factor {profit_factor:.3f} از حداقل {policy.min_profit_factor} بیشتر است."
        ),
        profit_factor,
        policy.min_profit_factor,
    ))

    drawdown_pct = _num(metrics.get("max_drawdown_pct"))
    dd_ok = drawdown_pct is not None and drawdown_pct <= policy.max_drawdown
    checks.append(_check(
        "MAX_DRAWDOWN",
        dd_ok,
        (
            f"حداکثر افت سرمایه {drawdown_pct:.2%} از سقف {policy.max_drawdown:.2%} بیشتر است."
            if drawdown_pct is not None and not dd_ok else
            "حداکثر افت سرمایه محاسبه نشده است."
            if drawdown_pct is None else
            f"حداکثر افت سرمایه {drawdown_pct:.2%} در سقف {policy.max_drawdown:.2%} است."
        ),
        drawdown_pct,
        policy.max_drawdown,
    ))

    if policy.require_positive_sharpe:
        sharpe = _num(metrics.get("sharpe"))
        checks.append(_check(
            "SHARPE_POSITIVE",
            sharpe is not None and sharpe > 0,
            (
                f"شارپ {sharpe:.3f} مثبت نیست." if sharpe is not None and sharpe <= 0
                else "شارپ محاسبه نشده است." if sharpe is None
                else f"شارپ {sharpe:.3f} مثبت است."
            ),
            sharpe,
            "> 0",
        ))

    calmar = _num(metrics.get("calmar"))
    if policy.min_calmar > 0:
        checks.append(_check(
            "CALMAR",
            calmar is not None and calmar >= policy.min_calmar,
            f"کالمار {calmar} از حداقل {policy.min_calmar} کمتر است."
            if calmar is None or calmar < policy.min_calmar
            else f"کالمار {calmar:.3f} از حداقل {policy.min_calmar} بیشتر است.",
            calmar,
            policy.min_calmar,
        ))

    ece = None
    if calibration:
        ece = _num(calibration.get("ece", calibration.get("expected_calibration_error")))
    if ece is not None:
        checks.append(_check(
            "CALIBRATION_ECE",
            ece <= policy.max_ece,
            (
                f"ECE {ece:.4f} از سقف {policy.max_ece} بیشتر است."
                if ece > policy.max_ece else
                f"ECE {ece:.4f} در سقف {policy.max_ece} است."
            ),
            ece,
            policy.max_ece,
        ))

    if train_metrics is not None and test_metrics is not None:
        train_pf = _num(train_metrics.get("profit_factor"))
        test_pf = _num(test_metrics.get("profit_factor"))
        if train_pf and train_pf > 0 and test_pf is not None:
            gap = max(0.0, (train_pf - test_pf) / train_pf)
            checks.append(_check(
                "TRAIN_TEST_GAP",
                gap <= policy.max_train_test_gap,
                (
                    f"افت Profit Factor از آموزش ({train_pf:.3f}) به آزمون ({test_pf:.3f}) "
                    f"برابر {gap:.0%} و بیش از سقف {policy.max_train_test_gap:.0%} است."
                    if gap > policy.max_train_test_gap else
                    f"افت آموزش→آزمون {gap:.0%} در سقف {policy.max_train_test_gap:.0%} است."
                ),
                round(gap, 4),
                policy.max_train_test_gap,
            ))
            if gap > policy.max_train_test_gap:
                anti.append(AntiPattern(
                    "OVERFIT_GAP",
                    "HIGH",
                    "عملکرد آموزش به‌شدت بهتر از آزمون است؛ نشانه برازش بیش‌ازحد.",
                ))

    costs = metrics.get("costs") or {}
    cost_total = _num(costs.get("total"), 0.0) or 0.0
    if trade_count > 0:
        checks.append(_check(
            "COSTS_MODELED",
            cost_total > 0,
            "هزینه‌های معاملاتی در بک‌تست صفر است؛ نتیجه بدون هزینه قابل پذیرش نیست.",
            cost_total,
            "> 0",
        ))
        if cost_total <= 0:
            anti.append(AntiPattern(
                "IGNORED_COSTS",
                "HIGH",
                "بک‌تست بدون اسپرد/کمیسیون/سواپ انجام شده است.",
            ))

    if not has_locked_test:
        anti.append(AntiPattern(
            "NO_LOCKED_TEST",
            "MEDIUM",
            "نتیجه Locked Test ندارد؛ خطر انتخاب سوگیرانه تنظیمات وجود دارد.",
        ))
    if not has_walkforward:
        anti.append(AntiPattern(
            "NO_WALKFORWARD",
            "MEDIUM",
            "اعتبارسنجی Walk-forward انجام نشده است.",
        ))
    if regime_breakdown:
        regimes = {
            key: value for key, value in regime_breakdown.items()
            if isinstance(value, Mapping) and int(_num(value.get("trade_count"), 0) or 0) > 0
        }
        if len(regimes) <= 1 and trade_count > 0:
            anti.append(AntiPattern(
                "SINGLE_REGIME",
                "MEDIUM",
                "همه معاملات در یک رژیم بازار رخ داده‌اند؛ تعمیم‌پذیری نامشخص است.",
            ))

    passed = not any(not check.passed for check in checks)
    thresholds = {
        "min_oos_trades": policy.min_oos_trades,
        "min_profit_factor": policy.min_profit_factor,
        "max_drawdown": policy.max_drawdown,
        "max_ece": policy.max_ece,
        "min_calmar": policy.min_calmar,
        "max_train_test_gap": policy.max_train_test_gap,
    }
    return AcceptanceReport(
        passed=passed,
        checks=tuple(checks),
        anti_patterns=tuple(anti),
        thresholds=thresholds,
    )


def evaluate_run(run, *, policy: AcceptancePolicy | None = None) -> AcceptanceReport:
    """ارزیابی یک `BacktestRun` ذخیره‌شده با استخراج شواهد موجود در metrics."""
    metrics = dict(getattr(run, "metrics", {}) or {})
    calibration = metrics.get("calibration") if isinstance(metrics, Mapping) else None
    regime = metrics.get("regime_breakdown") if isinstance(metrics, Mapping) else None
    segment = getattr(run, "segment", None)
    is_oos = True
    try:
        is_oos = str(getattr(segment, "value", segment) or "").upper() != "TRAIN"
    except Exception:
        is_oos = True
    return evaluate_acceptance(
        metrics,
        policy=policy,
        calibration=calibration if isinstance(calibration, Mapping) else None,
        regime_breakdown=regime if isinstance(regime, Mapping) else None,
        has_locked_test=bool(metrics.get("locked_test")),
        has_walkforward=bool(metrics.get("walkforward")),
        is_oos=is_oos,
    )
