"""پیش‌فرض‌های هوشمند تنظیمات معاملات بر اساس سرمایه حساب.

هدف: به‌جای اعداد ثابت، سقف حجم/تعداد پوزیشن/ریسک از روی equity و مشخصات
قراردادی نمادها محاسبه شود، اما هر مقدار همچنان توسط سیاست ریسک سخت‌گیرانه
(``settings.risk``) سقف‌گذاری و توسط کاربر قابل ویرایش است.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

from fxars.config.settings import AutomatedLimitedSettings, RiskPolicy
from fxars.core.numerics import ZERO

# فاصله حد ضرر نمونه هر تایم‌فریم (پیپ)؛ برای محاسبه سقف حجم و پله‌ها.
TF_TYPICAL_STOP_PIPS: dict[str, Decimal] = {
    "M5": Decimal("8"),
    "M15": Decimal("12"),
    "H1": Decimal("25"),
    "H4": Decimal("50"),
    "D1": Decimal("100"),
}
LADDER_STOPS_PIPS: tuple[int, ...] = (10, 20, 30, 50, 80, 120)
VALID_TIMEFRAMES: tuple[str, ...] = ("M5", "M15", "H1", "H4", "D1")
TRADABLE_INSTRUMENTS: tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
    "EURJPY", "GBPJPY", "XAUUSD",
)


@dataclass(frozen=True)
class CapitalProfile:
    key: str
    label: str
    min_equity: Decimal
    max_equity: Decimal | None
    risk_per_trade: Decimal
    max_open_positions: int
    max_daily_trades: int
    daily_loss_limit: Decimal
    drawdown_stop: Decimal
    max_spread_pips: Decimal
    timeframes: tuple[str, ...]
    instruments: tuple[str, ...]

    def contains(self, equity: Decimal) -> bool:
        if equity < self.min_equity:
            return False
        return self.max_equity is None or equity < self.max_equity


CAPITAL_PROFILES: tuple[CapitalProfile, ...] = (
    CapitalProfile(
        key="micro", label="خرد (زیر ۲۰۰ دلار)",
        min_equity=Decimal("0"), max_equity=Decimal("200"),
        risk_per_trade=Decimal("0.05"), max_open_positions=1, max_daily_trades=2,
        daily_loss_limit=Decimal("0.08"), drawdown_stop=Decimal("0.12"),
        max_spread_pips=Decimal("3.0"),
        timeframes=("M15", "H1"),
        instruments=("EURUSD", "GBPUSD", "USDJPY"),
    ),
    CapitalProfile(
        key="small", label="کوچک (۲۰۰ تا ۱۰۰۰ دلار)",
        min_equity=Decimal("200"), max_equity=Decimal("1000"),
        risk_per_trade=Decimal("0.02"), max_open_positions=2, max_daily_trades=3,
        daily_loss_limit=Decimal("0.06"), drawdown_stop=Decimal("0.12"),
        max_spread_pips=Decimal("3.0"),
        timeframes=("M15", "H1", "H4"),
        instruments=("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"),
    ),
    CapitalProfile(
        key="starter", label="شروع (۱۰۰۰ تا ۵۰۰۰ دلار)",
        min_equity=Decimal("1000"), max_equity=Decimal("5000"),
        risk_per_trade=Decimal("0.015"), max_open_positions=2, max_daily_trades=4,
        daily_loss_limit=Decimal("0.06"), drawdown_stop=Decimal("0.12"),
        max_spread_pips=Decimal("3.0"),
        timeframes=("M15", "H1", "H4"),
        instruments=("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"),
    ),
    CapitalProfile(
        key="standard", label="استاندارد (۵۰۰۰ تا ۲۵۰۰۰ دلار)",
        min_equity=Decimal("5000"), max_equity=Decimal("25000"),
        risk_per_trade=Decimal("0.01"), max_open_positions=2, max_daily_trades=5,
        daily_loss_limit=Decimal("0.05"), drawdown_stop=Decimal("0.12"),
        max_spread_pips=Decimal("3.0"),
        timeframes=("M15", "H1", "H4"),
        instruments=("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"),
    ),
    CapitalProfile(
        key="growth", label="رشد (۲۵۰۰۰ تا ۱۰۰۰۰۰ دلار)",
        min_equity=Decimal("25000"), max_equity=Decimal("100000"),
        risk_per_trade=Decimal("0.0075"), max_open_positions=3, max_daily_trades=6,
        daily_loss_limit=Decimal("0.04"), drawdown_stop=Decimal("0.10"),
        max_spread_pips=Decimal("2.5"),
        timeframes=("M15", "H1", "H4"),
        instruments=("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"),
    ),
    CapitalProfile(
        key="pro", label="حرفه‌ای (بالای ۱۰۰۰۰۰ دلار)",
        min_equity=Decimal("100000"), max_equity=None,
        risk_per_trade=Decimal("0.005"), max_open_positions=4, max_daily_trades=8,
        daily_loss_limit=Decimal("0.03"), drawdown_stop=Decimal("0.10"),
        max_spread_pips=Decimal("2.5"),
        timeframes=("M15", "H1", "H4"),
        instruments=("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"),
    ),
)


def select_profile(equity: Decimal | str | float | int) -> CapitalProfile:
    value = _dec(equity)
    for profile in CAPITAL_PROFILES:
        if profile.contains(value):
            return profile
    return CAPITAL_PROFILES[-1]


def pip_value_usd(instrument: Any) -> Decimal:
    """ارزش هر پیپ برای یک لات کامل به دلار، از مشخصات قراردادی نماد.

    ``tick_value`` در این نمادها به دلار است؛ تبدیل پیپ به tick با نسبت
    ``pip_size / tick_size`` انجام می‌شود (بدون نیاز به نرخ لحظه‌ای).
    """
    try:
        tick_size = _dec(instrument.tick_size)
        pip_size = _dec(instrument.pip_size)
        tick_value = _dec(instrument.tick_value)
    except Exception:
        return ZERO
    if tick_size <= ZERO or pip_size <= ZERO or tick_value <= ZERO:
        return ZERO
    return tick_value * (pip_size / tick_size)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _floor_lot(volume: Decimal, lot_step: Decimal) -> Decimal:
    if lot_step <= ZERO:
        lot_step = Decimal("0.01")
    return (volume / lot_step).to_integral_value(rounding=ROUND_DOWN) * lot_step


def _profile_caps(profile: CapitalProfile, policy: RiskPolicy) -> dict[str, Any]:
    risk = min(profile.risk_per_trade, policy.hard_cap_risk_per_trade)
    daily_loss = min(profile.daily_loss_limit, policy.daily_loss_limit)
    warn = policy.drawdown_warn
    drawdown = max(profile.drawdown_stop, warn + Decimal("0.02"))
    drawdown = min(drawdown, policy.max_drawdown_hard_cap)
    if drawdown <= warn:
        drawdown = min(policy.drawdown_stop, policy.max_drawdown_hard_cap)
    return {
        "risk_per_trade": risk,
        "daily_loss_limit": daily_loss,
        "drawdown_stop": drawdown,
        "max_open_positions": max(1, min(profile.max_open_positions, policy.max_open_positions)),
        "max_daily_trades": max(1, min(profile.max_daily_trades, policy.max_daily_trades)),
        "max_spread_pips": min(profile.max_spread_pips, policy.max_spread_pips),
    }


def _instrument_index(instruments: Iterable[Any]) -> dict[str, Any]:
    return {str(item.instrument_id).upper(): item for item in instruments}


def _selected_specs(ids: Iterable[str], index: dict[str, Any]) -> list[Any]:
    specs = [index[str(i).upper()] for i in ids if str(i).upper() in index]
    return specs


def recommend_trading_settings(
    equity: Decimal | str | float | int,
    policy: RiskPolicy,
    instruments: Iterable[Any],
    *,
    instrument_ids: Iterable[str] | None = None,
    timeframes: Iterable[str] | None = None,
) -> dict[str, Any]:
    """پیشنهاد تنظیمات معاملات برای سطح سرمایه؛ هرگز از سقف سیاست عبور نمی‌کند."""
    equity_value = max(ZERO, _dec(equity))
    profile = select_profile(equity_value)
    caps = _profile_caps(profile, policy)
    index = _instrument_index(instruments)

    selected_ids = list(instrument_ids) if instrument_ids else list(profile.instruments)
    selected_ids = [str(i).upper() for i in selected_ids if str(i).upper() in TRADABLE_INSTRUMENTS]
    selected_ids = [i for i in selected_ids if i in index] or list(profile.instruments)
    specs = _selected_specs(selected_ids, index)

    tfs = [str(tf).upper() for tf in (timeframes or profile.timeframes)]
    tfs = [tf for tf in tfs if tf in TF_TYPICAL_STOP_PIPS] or list(profile.timeframes)

    warnings: list[str] = []
    capped_fields: list[str] = []
    if caps["risk_per_trade"] < profile.risk_per_trade:
        capped_fields.append("risk_per_trade")
    if caps["daily_loss_limit"] < profile.daily_loss_limit:
        capped_fields.append("daily_loss_limit")
    if caps["max_open_positions"] < profile.max_open_positions:
        capped_fields.append("max_open_positions")
    if caps["max_daily_trades"] < profile.max_daily_trades:
        capped_fields.append("max_daily_trades")
    if capped_fields:
        warnings.append(
            "این مقادیر توسط سقف سیاست ریسک محدود شده‌اند: " + "، ".join(capped_fields)
        )

    pip_values = [pip_value_usd(spec) for spec in specs]
    pip_values = [value for value in pip_values if value > ZERO]
    pip_value_max = max(pip_values) if pip_values else Decimal("10")
    lot_steps = [_dec(spec.lot_step) for spec in specs if _dec(spec.lot_step) > ZERO]
    lot_step = max(lot_steps) if lot_steps else Decimal("0.01")
    min_lots = [_dec(spec.min_lot) for spec in specs if _dec(spec.min_lot) > ZERO]
    max_lots = [_dec(spec.max_lot) for spec in specs if _dec(spec.max_lot) > ZERO]
    min_lot = min(min_lots) if min_lots else Decimal("0.01")
    max_lot = min(max_lots) if max_lots else Decimal("100")
    stop_for_cap = min(TF_TYPICAL_STOP_PIPS[tf] for tf in tfs)
    risk = caps["risk_per_trade"]

    raw_volume = (
        equity_value * risk / (stop_for_cap * pip_value_max)
        if equity_value > ZERO and risk > ZERO and pip_value_max > ZERO
        else ZERO
    )
    recommended_volume = _floor_lot(raw_volume, lot_step)
    if recommended_volume < min_lot:
        required_equity = min_lot * stop_for_cap * pip_value_max / risk if risk > ZERO else ZERO
        warnings.append(
            f"با سرمایه {equity_value} حتی حداقل لات {min_lot} روی حد ضرر نمونه "
            f"{stop_for_cap} پیپ بیش از ریسک {risk * 100:.2f}٪ است؛ "
            f"حداقل سرمایه پیشنهادی ≈ {required_equity:.0f} دلار (یا حد ضرر نزدیک‌تر)."
        )
        recommended_volume = min_lot
    recommended_volume = min(recommended_volume, max_lot)

    ladder: list[dict[str, Any]] = []
    for stop in LADDER_STOPS_PIPS:
        stop_dec = Decimal(stop)
        volume = _floor_lot(equity_value * risk / (stop_dec * pip_value_max), lot_step) if equity_value > ZERO else ZERO
        below = volume < min_lot
        if below:
            volume = ZERO
        capped = volume > max_lot
        if capped:
            volume = max_lot
        estimated_risk = volume * stop_dec * pip_value_max
        ladder.append({
            "stop_pips": stop,
            "volume": str(volume),
            "estimated_risk": str(estimated_risk.quantize(Decimal("0.01"))),
            "below_min_lot": below,
            "capped": capped,
        })

    return {
        "profile": {
            "key": profile.key,
            "label": profile.label,
            "min_equity": str(profile.min_equity),
            "max_equity": None if profile.max_equity is None else str(profile.max_equity),
        },
        "equity": str(equity_value),
        "risk_per_trade": str(caps["risk_per_trade"]),
        "daily_loss_limit": str(caps["daily_loss_limit"]),
        "drawdown_stop": str(caps["drawdown_stop"]),
        "max_open_positions": caps["max_open_positions"],
        "max_daily_trades": caps["max_daily_trades"],
        "max_spread_pips": str(caps["max_spread_pips"]),
        "max_volume_per_order": str(recommended_volume),
        "timeframes": tfs,
        "instruments": selected_ids,
        "pip_value_usd": str(pip_value_max.quantize(Decimal("0.01"))),
        "typical_stop_pips": str(stop_for_cap),
        "ladder": ladder,
        "warnings": warnings,
        "capped_by_policy": capped_fields,
    }


def apply_automated_updates(
    current: AutomatedLimitedSettings, values: dict[str, Any],
) -> AutomatedLimitedSettings:
    """تبدیل ورودی API به تنظیمات جدید؛ فقط کلیدهای مجاز ویرایش‌پذیرند."""
    from dataclasses import replace

    allowed = {
        "max_volume_per_order", "max_open_positions", "max_daily_trades",
        "risk_per_trade", "daily_loss_limit", "drawdown_stop", "max_spread_pips",
        "instruments", "timeframes", "require_triggered_scenario",
    }
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"کلیدهای غیرمجاز در تنظیمات معاملات: {', '.join(unknown)}")

    changes: dict[str, Any] = {}
    if "max_volume_per_order" in values:
        changes["max_volume_per_order"] = _dec(values["max_volume_per_order"])
    if "risk_per_trade" in values:
        changes["risk_per_trade"] = _dec(values["risk_per_trade"])
    if "daily_loss_limit" in values:
        changes["daily_loss_limit"] = _dec(values["daily_loss_limit"])
    if "drawdown_stop" in values:
        changes["drawdown_stop"] = _dec(values["drawdown_stop"])
    if "max_spread_pips" in values:
        changes["max_spread_pips"] = _dec(values["max_spread_pips"])
    for key in ("max_open_positions", "max_daily_trades"):
        if key in values:
            changes[key] = int(values[key])
    if "instruments" in values:
        items = values["instruments"]
        if isinstance(items, str):
            items = [item.strip() for item in items.split(",") if item.strip()]
        changes["instruments"] = tuple(dict.fromkeys(str(item).upper() for item in items or ()))
    if "timeframes" in values:
        items = values["timeframes"]
        if isinstance(items, str):
            items = [item.strip() for item in items.split(",") if item.strip()]
        changes["timeframes"] = tuple(dict.fromkeys(str(item).upper() for item in items or ()))
    if "require_triggered_scenario" in values:
        changes["require_triggered_scenario"] = bool(values["require_triggered_scenario"])
    return replace(current, **changes)


def validate_automated_settings_soft(
    automated: AutomatedLimitedSettings, policy: RiskPolicy, instruments: Iterable[Any],
) -> tuple[list[str], list[str]]:
    """اعتبارسنجی دو سطحی: خطاهای ساختاری و هشدارهای عبور از سقف سیاست.

    خطا یعنی مقدار قابل اجرا نیست (صفر/منفی، تایم‌فریم ناشناخته، نماد بدون
    مشخصات). هشدار یعنی مقدار معتبر است اما از پیشنهاد/سقف سیاست بیرون است و
    فقط با تأیید صریح کاربر ذخیره می‌شود.
    """
    errors: list[str] = []
    warnings: list[str] = []
    index = _instrument_index(instruments)

    if automated.max_volume_per_order <= ZERO:
        errors.append("حداکثر حجم هر سفارش باید مثبت باشد.")
    if automated.risk_per_trade <= ZERO:
        errors.append("ریسک هر معامله باید مثبت باشد.")
    elif automated.risk_per_trade > policy.hard_cap_risk_per_trade:
        warnings.append(
            f"ریسک هر معامله {automated.risk_per_trade * 100:.2f}% از سقف سیاست "
            f"({policy.hard_cap_risk_per_trade * 100:.2f}%) بیشتر است."
        )
    if automated.daily_loss_limit <= ZERO:
        errors.append("سقف زیان روزانه باید مثبت باشد.")
    elif automated.daily_loss_limit > policy.daily_loss_limit:
        warnings.append(
            f"سقف زیان روزانه {automated.daily_loss_limit * 100:.2f}% از پیشنهاد سیاست "
            f"({policy.daily_loss_limit * 100:.2f}%) بیشتر است."
        )
    if automated.drawdown_stop <= ZERO:
        errors.append("حد توقف افت سرمایه باید مثبت باشد.")
    else:
        if automated.drawdown_stop <= policy.drawdown_warn:
            warnings.append(
                f"حد توقف افت سرمایه ({automated.drawdown_stop * 100:.2f}%) از آستانه هشدار "
                f"({policy.drawdown_warn * 100:.2f}%) بزرگ‌تر نیست."
            )
        if automated.drawdown_stop > policy.max_drawdown_hard_cap:
            warnings.append(
                f"حد توقف افت سرمایه از سقف سخت سیاست "
                f"({policy.max_drawdown_hard_cap * 100:.2f}%) بیشتر است."
            )
    if automated.max_open_positions < 1:
        errors.append("تعداد پوزیشن باز باید حداقل ۱ باشد.")
    elif automated.max_open_positions > policy.max_open_positions:
        warnings.append(
            f"تعداد پوزیشن باز ({automated.max_open_positions}) از سقف سیاست "
            f"({policy.max_open_positions}) بیشتر است."
        )
    if automated.max_daily_trades < 1:
        errors.append("تعداد معاملات روزانه باید حداقل ۱ باشد.")
    elif automated.max_daily_trades > policy.max_daily_trades:
        warnings.append(
            f"تعداد معاملات روزانه ({automated.max_daily_trades}) از سقف سیاست "
            f"({policy.max_daily_trades}) بیشتر است."
        )
    if automated.max_spread_pips <= ZERO:
        errors.append("حداکثر اسپرد باید مثبت باشد.")
    elif automated.max_spread_pips > policy.max_spread_pips:
        warnings.append(
            f"حداکثر اسپرد ({automated.max_spread_pips}) از پیشنهاد سیاست "
            f"({policy.max_spread_pips}) پیپ بیشتر است."
        )

    selected = [str(item).upper() for item in automated.instruments]
    if not selected:
        errors.append("حداقل یک نماد معاملاتی انتخاب کنید.")
    missing = [item for item in selected if item not in index]
    if missing:
        errors.append(
            "نماد(های) بدون مشخصات در پایگاه داده: " + "، ".join(missing)
        )
    extra = [item for item in selected if item in index and item not in TRADABLE_INSTRUMENTS]
    if extra:
        warnings.append(
            "نماد(های) خارج از فهرست پیشنهادی: " + "، ".join(extra)
        )

    tfs = [str(item).upper() for item in automated.timeframes]
    if not tfs:
        errors.append("حداقل یک تایم‌فریم انتخاب کنید.")
    invalid_tfs = [item for item in tfs if item not in VALID_TIMEFRAMES]
    if invalid_tfs:
        errors.append("تایم‌فریم(های) ناشناخته: " + "، ".join(invalid_tfs))

    specs = _selected_specs(selected, index)
    max_lots = [_dec(spec.max_lot) for spec in specs if _dec(spec.max_lot) > ZERO]
    if max_lots and automated.max_volume_per_order > min(max_lots):
        warnings.append(
            f"حداکثر حجم از سقف مجاز نمادها ({min(max_lots)}) بیشتر است."
        )
    return errors, warnings


def validate_automated_settings(
    automated: AutomatedLimitedSettings, policy: RiskPolicy, instruments: Iterable[Any],
) -> list[str]:
    """حالت سخت‌گیرانهٔ سازگار با نسخهٔ قبل: خطاها و هشدارها یک‌جا برمی‌گردند."""
    errors, warnings = validate_automated_settings_soft(automated, policy, instruments)
    return errors + warnings
