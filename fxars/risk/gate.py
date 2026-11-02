"""دروازه ریسک: لایه مستقل، اجباری و غیرقابل دور زدن (بخش ۹).

هیچ OrderIntent یا تصمیم اجرایی بدون RiskDecision معتبر مجاز نیست. در MVP-1 فقط
ارزیابی و اندازه موقعیت پیشنهادی انجام می‌شود و سفارشی ارسال نمی‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fxars.config.settings import RiskPolicy
from fxars.core.context import current_correlation_id
from fxars.core.hashing import sha256_obj
from fxars.core.ids import stable_id
from fxars.core.numerics import ZERO, quantize, to_decimal
from fxars.core.timeutil import ensure_utc
from fxars.domain.enums import Direction, RiskReasonCode, ScenarioStatus
from fxars.domain.models import (
    AccountSnapshot,
    Candle,
    EconomicEvent,
    Instrument,
    RiskCheck,
    RiskDecision,
    Scenario,
)
from fxars.instruments.calendar import TradingCalendar
from fxars.risk import exposure as exposure_tools
from fxars.risk.killswitch import KillSwitch
from fxars.risk.sizing import SizingInput, SizingResult, calculate_position_size

CHECK_TO_REASON: dict[str, RiskReasonCode] = {
    "scenario_valid": RiskReasonCode.SCENARIO_INVALID,
    "signal_strength": RiskReasonCode.SIGNAL_TOO_WEAK,
    "policy_present": RiskReasonCode.POLICY_MISSING,
    "kill_switch_inactive": RiskReasonCode.KILL_SWITCH_ACTIVE,
    "instrument_spec_valid": RiskReasonCode.INSTRUMENT_SPEC_INVALID,
    "account_snapshot_fresh": RiskReasonCode.ACCOUNT_SNAPSHOT_STALE,
    "data_fresh": RiskReasonCode.STALE_DATA,
    "price_valid": RiskReasonCode.PRICE_INVALID,
    "stop_distance_within_limits": RiskReasonCode.STOP_DISTANCE_INVALID,
    "position_size_valid": RiskReasonCode.POSITION_SIZE_INVALID,
    "risk_per_trade_within_limit": RiskReasonCode.RISK_PER_TRADE_EXCEEDED,
    "daily_loss_within_limit": RiskReasonCode.DAILY_LOSS_LIMIT,
    "drawdown_within_limit": RiskReasonCode.DRAWDOWN_LIMIT,
    "max_open_trades_ok": RiskReasonCode.MAX_OPEN_TRADES,
    "symbol_exposure_ok": RiskReasonCode.SYMBOL_EXPOSURE_LIMIT,
    "currency_exposure_ok": RiskReasonCode.CURRENCY_EXPOSURE_LIMIT,
    "correlation_exposure_ok": RiskReasonCode.CORRELATION_EXPOSURE_LIMIT,
    "event_blackout_ok": RiskReasonCode.EVENT_BLACKOUT,
    "spread_within_limit": RiskReasonCode.SPREAD_LIMIT,
    "margin_sufficient": RiskReasonCode.MARGIN_INSUFFICIENT,
    "validity_window_ok": RiskReasonCode.SCENARIO_EXPIRED,
    "entry_deviation_ok": RiskReasonCode.PRICE_INVALID,
}


@dataclass(frozen=True)
class RiskContext:
    scenario: Scenario
    account: AccountSnapshot | None
    instrument: Instrument | None
    candle: Candle | None
    events: tuple[EconomicEvent, ...]
    instruments: dict[str, Instrument]
    rates: dict[str, Decimal]
    correlations: dict[str, float]
    now: datetime


class RiskGate:
    def __init__(self, policy: RiskPolicy, killswitch: KillSwitch, calendar: TradingCalendar | None = None) -> None:
        self.policy = policy
        self.killswitch = killswitch
        self.calendar = calendar or TradingCalendar()

    def evaluate(self, context: RiskContext) -> RiskDecision:
        policy = self.policy
        now = ensure_utc(context.now)
        checks: list[RiskCheck] = []

        def add(code: str, passed: bool, detail: str, value: Any = None, limit: Any = None) -> None:
            checks.append(RiskCheck(code=code, passed=bool(passed), detail=detail,
                                    value=None if value is None else str(value),
                                    limit=None if limit is None else str(limit)))

        scenario = context.scenario
        instrument = context.instrument
        account = context.account
        candle = context.candle

        entry = to_decimal(scenario.entry_condition.get("level", "0"))
        stop = scenario.stop_level or ZERO
        targets = scenario.target_logic
        target = to_decimal(targets[0]["price"]) if targets and targets[0].get("price") else None
        side = "BUY" if scenario.direction is Direction.LONG else "SELL"

        add("policy_present", bool(policy.version), "نسخه سیاست ریسک موجود است.", policy.version, "required")
        add("kill_switch_inactive", not self.killswitch.is_active(), "Kill Switch فعال نیست.",
            self.killswitch.status().get("active"), False)
        add("scenario_valid",
            scenario.direction in (Direction.LONG, Direction.SHORT) and entry > ZERO and stop > ZERO
            and scenario.expiry_at > now and scenario.status in (ScenarioStatus.WATCH, ScenarioStatus.ARMED, ScenarioStatus.TRIGGERED),
            "سناریو دارای جهت، ورود، حد ضرر و انقضای معتبر است.",
            {"status": scenario.status.value, "entry": str(entry), "stop": str(stop)})
        add("signal_strength", scenario.strength >= policy.min_signal_strength,
            "قدرت سیگنال از حداقل مصوب کمتر نیست.", round(scenario.strength, 4), policy.min_signal_strength)
        add("instrument_spec_valid",
            instrument is not None and instrument.is_valid_at(now) and instrument.contract_size > ZERO
            and instrument.pip_size > ZERO and instrument.lot_step > ZERO,
            "مشخصات قراردادی نماد معتبر و در تاریخ اعتبار است.",
            instrument.instrument_id if instrument else None)
        # FIX-06-RISK-FAIL-CLOSED: حساب آینده یا خارج از TTL ⇒ Fail
        account_age: float | None = None
        if account is not None:
            account_age = (now - account.taken_at).total_seconds()
        account_fresh = (account_age is not None and -5.0 <= account_age <= policy.max_account_age_seconds)
        add("account_snapshot_fresh", account_fresh,
            "تصویر حساب تازه است." if account_fresh else "تصویر حساب تازه نیست یا در آینده است.",
            None if account_age is None else round(account_age, 1), policy.max_account_age_seconds)

        stale = True
        if candle is not None:
            stale = self.calendar.is_stale(candle.available_at, now, candle.timeframe,
                                           grace_seconds=300, max_age_bars=1.5)
        add("data_fresh", candle is not None and not stale, "داده بازار تازه است.",
            None if candle is None else candle.available_at.isoformat(), f"<= {policy.max_account_age_seconds}s")

        price_ok = bool(
            candle is not None and candle.close > ZERO and entry > ZERO and stop > ZERO
            and ((scenario.direction is Direction.LONG and stop < entry) or (scenario.direction is Direction.SHORT and stop > entry))
        )
        add("price_valid", price_ok, "قیمت ورود/حد ضرر در جهت صحیح است.",
            {"entry": str(entry), "stop": str(stop), "close": str(candle.close) if candle else None})

        spread_pips: Decimal | None = None
        if candle is not None and candle.spread is not None and instrument is not None:
            spread_pips = candle.spread / instrument.pip_size
        # FIX-06: نبود اسپرد ⇒ Fail
        spread_ok = spread_pips is not None and spread_pips <= policy.max_spread_pips
        add("spread_within_limit", spread_ok,
            "اسپرد در محدوده مجاز است." if spread_ok else "اسپرد ناموجود یا خارج از سقف؛ تأیید نمی‌شود.",
            None if spread_pips is None else quantize(spread_pips, 2), policy.max_spread_pips)

        sizing: SizingResult | None = None
        if instrument is not None and account is not None and entry > ZERO and stop > ZERO:
            rate = to_decimal(context.rates.get(instrument.quote_currency, "1")) if instrument.quote_currency != account.currency else Decimal("1")
            sizing = calculate_position_size(
                SizingInput(
                    equity=account.equity,
                    risk_fraction=policy.risk_per_trade,
                    entry_price=entry,
                    stop_price=stop,
                    instrument=instrument,
                    quote_to_account_rate=rate,
                )
            )
        stop_pips = sizing.stop_pips if sizing else ZERO
        add("stop_distance_within_limits", sizing is not None and policy.min_stop_pips <= stop_pips <= policy.max_stop_pips,
            "فاصله حد ضرر در محدوده مجاز است.", quantize(stop_pips, 2) if sizing else None,
            f"{policy.min_stop_pips}..{policy.max_stop_pips} pip")
        add("position_size_valid", sizing is not None and sizing.valid and sizing.volume > ZERO,
            "اندازه موقعیت پس از گرد کردن معتبر است.",
            None if sizing is None else sizing.volume, f"min {instrument.min_lot if instrument else '-'}")
        add("risk_per_trade_within_limit",
            sizing is not None and account is not None and policy.risk_per_trade <= policy.hard_cap_risk_per_trade
            and sizing.estimated_loss_at_stop <= account.equity * policy.hard_cap_risk_per_trade + Decimal("0.01"),
            "ریسک هر معامله از سقف سخت عبور نمی‌کند.",
            None if sizing is None else sizing.estimated_loss_at_stop,
            None if account is None else account.equity * policy.hard_cap_risk_per_trade)

        daily_limit = account.max_daily_loss if account and account.max_daily_loss is not None else policy.daily_loss_limit
        add("daily_loss_within_limit",
            account is not None and account.daily_pnl >= -(account.equity * daily_limit),
            "زیان روزانه از حد مجاز عبور نکرده است.",
            None if account is None else account.daily_pnl,
            None if account is None else -(account.equity * daily_limit))

        drawdown_limit = account.max_drawdown if account and account.max_drawdown is not None else policy.drawdown_stop
        add("drawdown_within_limit",
            account is not None and account.drawdown_fraction <= drawdown_limit,
            "افت سرمایه از حد توقف عبور نکرده است.",
            None if account is None else quantize(account.drawdown_fraction * Decimal(100), 2), drawdown_limit * 100)

        positions = list(account.positions) if account else []
        same_symbol = sum(1 for position in positions if position.instrument_id == scenario.instrument_id)
        add("max_open_trades_ok",
            account is not None and account.open_positions < policy.max_open_positions and same_symbol < policy.max_positions_per_symbol,
            "تعداد معاملات باز در حد مجاز است.",
            {"open": None if account is None else account.open_positions, "symbol": same_symbol},
            {"max_open": policy.max_open_positions, "max_per_symbol": policy.max_positions_per_symbol})

        # FIX-06: عدم امکان محاسبه مواجهه ⇒ Fail
        exposures: dict[str, Decimal] = {}
        can_compute = (account is not None and instrument is not None
                       and sizing is not None and sizing.volume > ZERO)
        if can_compute:
            exposure_ok, exposures = exposure_tools.combined_currency_ok(
                positions, context.instruments, context.rates, instrument, sizing.volume, entry, side,
                account.equity * policy.max_currency_exposure,
            )
        else:
            exposure_ok = False
        add("currency_exposure_ok", exposure_ok,
            "مواجهه خالص ارزها در سقف مجاز است." if exposure_ok else "محاسبه مواجهه ارزی ممکن یا در محدوده نیست.",
            {key: str(quantize(value, 2)) for key, value in exposures.items()},
            None if account is None else account.equity * policy.max_currency_exposure)

        correlation_ok = True
        correlated = ZERO
        if account is not None and instrument is not None and sizing is not None and sizing.volume > ZERO:
            correlated = exposure_tools.correlated_margin(
                positions, context.instruments, context.rates, context.correlations, policy.correlation_threshold,
            )
            new_margin = exposure_tools.margin_required(
                instrument, sizing.volume, entry, to_decimal(context.rates.get(instrument.quote_currency, "1"))
                if instrument.quote_currency != account.currency else Decimal("1"),
            )
            correlation_ok = correlated + new_margin <= account.equity * policy.max_correlation_exposure
            add("correlation_exposure_ok", correlation_ok, "مواجهه نمادهای هم‌بسته در سقف مجاز است.",
                str(quantize(correlated + new_margin, 2)), account.equity * policy.max_correlation_exposure)
        else:
            add("correlation_exposure_ok", False, "امکان محاسبه مواجهه همبسته وجود ندارد.", None)

        blackout_ok = True
        blackout_details: list[str] = []
        if instrument is not None:
            for event in context.events:
                if event.importance.rank < policy.blackout_min_importance.rank:
                    continue
                if event.currency not in (instrument.base_currency, instrument.quote_currency):
                    continue
                if event.in_window(now, policy.blackout_before_minutes, policy.blackout_after_minutes):
                    blackout_ok = False
                    blackout_details.append(event.event_id)
        add("event_blackout_ok", blackout_ok, "پنجره ممنوعه خبری فعال نیست.",
            blackout_details, f"±{policy.blackout_before_minutes}min")

        margin_ok = False
        required_margin = ZERO
        if account is not None and instrument is not None and sizing is not None and sizing.volume > ZERO:
            rate = to_decimal(context.rates.get(instrument.quote_currency, "1")) if instrument.quote_currency != account.currency else Decimal("1")
            required_margin = exposure_tools.margin_required(instrument, sizing.volume, entry, rate)
            margin_ok = required_margin <= account.free_margin * (Decimal("1") - policy.margin_buffer)
        add("margin_sufficient", margin_ok, "مارجین آزاد پس از ذخیره حاشیه امن کافی است.",
            quantize(required_margin, 2), None if account is None else quantize(account.free_margin * (Decimal(1) - policy.margin_buffer), 2))

        add("validity_window_ok", now < scenario.expiry_at, "سناریو منقضی نشده است.",
            scenario.expiry_at.isoformat(), now.isoformat())

        # FIX-06: کنترل انحراف قیمت از Entry
        entry_dev_ok = False
        entry_dev_pips: float | None = None
        if candle is not None and instrument is not None and entry > ZERO:
            dev_pips = abs(candle.close - entry) / instrument.pip_size
            entry_dev_pips = float(dev_pips)
            entry_dev_ok = dev_pips <= Decimal("25")
        add("entry_deviation_ok", entry_dev_ok,
            "قیمت جاری نزدیک سطح ورود است." if entry_dev_ok else "قیمت از سطح ورود فاصله زیادی دارد.",
            entry_dev_pips, "25 pip")

        failed = [check for check in checks if not check.passed]
        approved = not failed
        reason_code = RiskReasonCode.APPROVED if approved else CHECK_TO_REASON.get(failed[0].code, RiskReasonCode.SCENARIO_INVALID)
        reason_detail = (
            "همه کنترل‌های ریسک عبور کردند." if approved
            else "؛ ".join(f"{check.code}: {check.detail}" for check in failed[:3])
        )
        inputs_hash = sha256_obj(
            {
                "scenario": scenario.to_dict(),
                "account": account.to_dict() if account else None,
                "instrument": instrument.to_dict() if instrument else None,
                "candle": candle.digest() if candle else None,
                "policy": policy.to_dict(),
                "rates": {key: str(value) for key, value in context.rates.items()},
                "correlations": context.correlations,
                "now": now,
            }
        )
        decision_id = stable_id("rd", inputs_hash, length=24)
        return RiskDecision(
            decision_id=decision_id,
            scenario_id=scenario.scenario_id,
            instrument_id=scenario.instrument_id,
            account_snapshot_id=account.snapshot_id if account else "",
            approved=approved,
            risk_amount=sizing.risk_amount if sizing else ZERO,
            risk_currency=account.currency if account else "USD",
            position_size=sizing.volume if sizing else ZERO,
            entry_price=entry,
            stop_loss=stop,
            take_profit=target,
            checks=tuple(checks),
            policy_version=policy.version,
            reason_code=reason_code,
            reason_detail=reason_detail,
            valid_until=now + timedelta(seconds=policy.decision_ttl_seconds),
            created_at=now,
            inputs_hash=inputs_hash,
            correlation_id=current_correlation_id(),
        )
