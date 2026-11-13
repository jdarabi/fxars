"""قواعد مشترک سقف اجرا برای فازهای DEMO/ASSISTED/AUTOMATED_LIMITED.

یک تابع خالص تا مسیر API، daemon و سرویس استراتژی همگی دقیقاً یک سیاست را
اعمال کنند و هیچ مسیری سقف‌ها را دور نزند.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fxars.config.settings import AutomatedLimitedSettings
from fxars.core.numerics import ZERO
from fxars.domain.enums import Phase, ScenarioStatus


@dataclass(frozen=True)
class ExecutionLimitInput:
    phase: Phase
    execute_orders: bool
    execution_enabled: bool
    killswitch_active: bool
    broker_is_real: bool
    position_size: Decimal
    automated: AutomatedLimitedSettings | None
    instrument: str
    timeframe: str
    scenario_status: ScenarioStatus | None
    spread_pips: Decimal | None
    max_spread_pips: Decimal
    open_positions: int
    trades_today: int | None
    paper_broker: bool = False


def execution_block_reason(limits: ExecutionLimitInput) -> str | None:
    """دلیل مسدودبودن ارسال؛ None یعنی همه سقف‌ها رعایت شده‌اند."""
    if not limits.execute_orders:
        return "EXECUTE_DISABLED"
    phase = limits.phase
    if phase is Phase.PAPER:
        # PAPER فقط با بروکر شبیه‌ساز مجاز است؛ هرگز با بروکر واقعی.
        if not limits.paper_broker:
            return "PAPER_BROKER_UNAVAILABLE"
    else:
        if phase not in (Phase.DEMO, Phase.ASSISTED, Phase.AUTOMATED_LIMITED):
            return f"PHASE_{phase.value}"
        if not limits.broker_is_real:
            return "REAL_BROKER_UNAVAILABLE"
    if not limits.execution_enabled:
        return "EXECUTION_DISABLED"
    if limits.killswitch_active:
        return "KILL_SWITCH_ACTIVE"
    if limits.position_size <= ZERO:
        return "POSITION_SIZE_ZERO"
    if limits.spread_pips is None:
        return "SPREAD_UNAVAILABLE"
    if limits.spread_pips > limits.max_spread_pips:
        return f"SPREAD_{limits.spread_pips:.2f}>{limits.max_spread_pips}"

    automated = limits.automated
    if automated is None:
        return "AUTOMATED_SETTINGS_MISSING" if phase is Phase.AUTOMATED_LIMITED else None
    if phase is not Phase.AUTOMATED_LIMITED:
        return None

    if not automated.enabled:
        return "AUTOMATED_DISABLED"
    if automated.killed:
        return "AUTOMATED_KILLED"
    allowed_instruments = {item.upper() for item in automated.instruments or ()}
    if allowed_instruments and limits.instrument.upper() not in allowed_instruments:
        return "INSTRUMENT_NOT_ALLOWED"
    allowed_timeframes = {item.upper() for item in automated.timeframes or ()}
    if allowed_timeframes and limits.timeframe.upper() not in allowed_timeframes:
        return "TIMEFRAME_NOT_ALLOWED"
    if automated.require_triggered_scenario and limits.scenario_status is not ScenarioStatus.TRIGGERED:
        return "SCENARIO_NOT_TRIGGERED"
    if limits.position_size > automated.max_volume_per_order:
        return f"VOLUME_{limits.position_size}>{automated.max_volume_per_order}"
    if limits.open_positions >= automated.max_open_positions:
        return "MAX_OPEN_POSITIONS"
    if limits.trades_today is None:
        return "TRADE_COUNT_UNAVAILABLE"
    if limits.trades_today >= automated.max_daily_trades:
        return "MAX_DAILY_TRADES"
    return None
