"""سرویس ریسک: آماده‌سازی زمینه، اجرای دروازه، ثبت تصمیم و رویداد."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fxars.audit.audit import AuditAction, AuditLog
from fxars.audit.outbox import EventType, Outbox
from fxars.config.settings import Settings
from fxars.core.errors import NotFoundError
from fxars.core.numerics import ZERO, floor_to_step, quantize, to_decimal
from fxars.domain.models import AccountSnapshot, Instrument, RiskCheck, RiskDecision
from fxars.instruments.calendar import TradingCalendar
from fxars.risk.account import parse_account_snapshot
from fxars.risk.gate import RiskContext, RiskGate
from fxars.risk.killswitch import KillSwitch
from fxars.risk.lock_lifecycle import RiskLockMachine
from fxars.storage.repositories import (
    AccountRepository,
    CandleRepository,
    ClosedTradeRepository,
    EconomicEventRepository,
    InstrumentRepository,
    OrderRepository,
    RiskRepository,
    ScenarioRepository,
)


def _cap_decision_volume(
    decision: RiskDecision, cap: Decimal | None, instrument: Instrument | None,
) -> RiskDecision:
    """حجم تأییدشده را به سقف فاز کاهش می‌دهد (هرگز افزایش نمی‌دهد)."""
    if not decision.approved or cap is None or decision.position_size <= ZERO:
        return decision
    try:
        cap_value = to_decimal(cap)
    except (TypeError, ValueError):
        return decision
    if cap_value <= ZERO or decision.position_size <= cap_value:
        return decision
    lot_step = instrument.lot_step if instrument is not None else Decimal("0.01")
    min_lot = instrument.min_lot if instrument is not None else Decimal("0.01")
    volume = floor_to_step(cap_value, lot_step)
    if volume < min_lot:
        # سقف از حداقل لات کوچک‌تر است؛ اجرا به‌صورت Fail-Closed رد می‌کند.
        return decision
    risk_amount = quantize(decision.risk_amount * volume / decision.position_size, 2)
    checks = tuple(
        replace(check, value=str(volume))
        if check.code == "position_size_valid" else check
        for check in decision.checks
    ) + (
        RiskCheck(
            code="phase_volume_cap",
            passed=True,
            detail=f"حجم از {decision.position_size} به سقف فاز {cap_value} کاهش یافت.",
            value=str(volume),
            limit=str(cap_value),
        ),
    )
    return replace(
        decision,
        position_size=volume,
        risk_amount=risk_amount,
        checks=checks,
        reason_detail=(
            f"{decision.reason_detail} حجم سفارش به سقف فاز {cap_value} کاهش یافت."
        ),
    )


class RiskService:
    def __init__(
        self,
        *,
        settings: Settings,
        clock: Callable[[], datetime],
        gate: RiskGate,
        killswitch: KillSwitch,
        scenarios: ScenarioRepository,
        instruments: InstrumentRepository,
        candles: CandleRepository,
        events: EconomicEventRepository,
        decisions: RiskRepository,
        accounts: AccountRepository,
        audit: AuditLog,
        outbox: Outbox,
        calendar: TradingCalendar,
        orders: OrderRepository | None = None,
        trades: ClosedTradeRepository | None = None,
        risk_lock: RiskLockMachine | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.gate = gate
        self.killswitch = killswitch
        self.scenarios = scenarios
        self.instruments = instruments
        self.candles = candles
        self.events = events
        self.decisions = decisions
        self.accounts = accounts
        self.audit = audit
        self.outbox = outbox
        self.calendar = calendar
        self.orders = orders
        self.trades = trades
        self.risk_lock = risk_lock

    def evaluate(
        self,
        scenario_id: str,
        account: AccountSnapshot | dict[str, Any] | None,
        *,
        rates: dict[str, Any] | None = None,
        now: datetime | None = None,
        actor: str = "system",
        trades_today: int | None = None,
        candle: Any | None = None,
        tenant_id: str | None = None,
        risk_fraction: Decimal | None = None,
        max_volume: Decimal | None = None,
    ) -> RiskDecision:
        moment = now or self.clock()
        scenario = self.scenarios.get(scenario_id)
        if tenant_id is not None and scenario.tenant_id != tenant_id:
            raise NotFoundError(f"سناریو {scenario_id} یافت نشد.", details={"scenario_id": scenario_id})
        instrument = self.instruments.find(scenario.instrument_id)
        snapshot = self._account(account, moment)
        snapshot = self._with_persisted_peak(snapshot)
        weekly_loss = self._weekly_loss_fraction(snapshot, scenario.tenant_id, moment)
        self._refresh_risk_lock(snapshot, weekly_loss, moment)
        if trades_today is None and self.orders is not None:
            day_start = (
                self.calendar.trading_day_start(moment)
                if self.calendar is not None and hasattr(self.calendar, "trading_day_start")
                else moment.replace(hour=0, minute=0, second=0, microsecond=0)
            )
            trades_today = self.orders.count_intents_since(day_start)
        trades_today = int(trades_today or 0)
        if candle is None:
            if instrument is not None:
                # PRIMARY_SOURCE_RISK: انتخاب منبع اصلی برای ریسک
                try:
                    primary_source = self.instruments.primary_source(scenario.instrument_id, scenario.timeframe)
                except Exception:
                    primary_source = None
                candles = self.candles.range(
                    scenario.instrument_id, scenario.timeframe, source_id=primary_source,
                    as_of=moment, closed_only=True,
                )
                candle = candles[-1] if candles else None
        events = self.events.between(moment - timedelta(days=1), moment + timedelta(days=2), as_of=None)
        instruments = {instrument.instrument_id: instrument} if instrument else {}
        if snapshot is not None:
            for position in snapshot.positions:
                found = self.instruments.find(position.instrument_id)
                if found is not None:
                    instruments[position.instrument_id] = found
        correlations = self._correlations(scenario.instrument_id, list(instruments), scenario.timeframe, moment)
        rate_map: dict[str, Decimal] = {}
        for key, value in (rates or {}).items():
            try:
                rate_map[str(key).upper()] = to_decimal(value)
            except (TypeError, ValueError):
                # نرخ نامعتبر عمداً حذف می‌شود تا RiskGate به‌صورت Fail-Closed رد کند.
                continue

        context = RiskContext(
            scenario=scenario,
            account=snapshot,
            instrument=instrument,
            candle=candle,
            events=tuple(events),
            instruments=instruments,
            rates=rate_map,
            correlations=correlations,
            now=moment,
            trades_today=trades_today,
            weekly_loss_fraction=weekly_loss,
        )
        decision = self.gate.evaluate(context, policy=self._effective_policy(risk_fraction))
        decision = _cap_decision_volume(decision, max_volume, instrument)
        if decision.tenant_id != scenario.tenant_id:
            decision = replace(decision, tenant_id=scenario.tenant_id)

        with self.scenarios.db.transaction():
            if snapshot is not None:
                self.accounts.save(snapshot)
            self.decisions.save(decision)
            if decision.approved:
                updated = replace(scenario, risk_decision_id=decision.decision_id, updated_at=moment)
                self.scenarios.save(updated)
            self.audit.append(
                AuditAction.RISK_EVALUATED,
                "risk_decision",
                decision.decision_id,
                actor=actor,
                payload={
                    "scenario_id": scenario_id,
                    "approved": decision.approved,
                    "reason_code": decision.reason_code.value,
                    "position_size": str(decision.position_size),
                    "risk_amount": str(decision.risk_amount),
                    "checks_failed": list(decision.checks_failed),
                },
            )
            self.outbox.emit(
                EventType.RISK_EVALUATED,
                {
                    "decision_id": decision.decision_id,
                    "scenario_id": scenario_id,
                    "approved": decision.approved,
                    "reason_code": decision.reason_code.value,
                    "position_size": str(decision.position_size),
                },
                occurred_at=moment,
            )
        return decision

    def _weekly_loss_fraction(
        self,
        snapshot: AccountSnapshot | None,
        tenant_id: str | None,
        moment: datetime,
    ) -> Decimal:
        """نسبت زیان هفتگی محقق‌شده از معاملات بسته‌شده تا ابتدای هفته سشن."""
        if snapshot is None or snapshot.equity <= ZERO or self.trades is None:
            return ZERO
        if self.calendar is not None and hasattr(self.calendar, "week_open"):
            start = self.calendar.week_open(moment)
        else:
            start = moment - timedelta(days=7)
        try:
            closed = self.trades.list(tenant_id=tenant_id or "default", since=start, limit=1000)
        except Exception:
            # FIX-08-WEEKLY-LOSS-FALLBACK: اگر closed_trades در دسترس نیست،
            # از daily_pnl (از بروکر) به‌عنوان تخمین محافظه‌کارانه استفاده کن.
            if snapshot.daily_pnl < ZERO:
                return min(Decimal("1"), (-snapshot.daily_pnl) / snapshot.equity)
            return ZERO
        net = sum((trade.net_profit for trade in closed), ZERO)
        if net >= ZERO:
            return ZERO
        return min(Decimal("1"), (-net) / snapshot.equity)

    def _refresh_risk_lock(
        self,
        snapshot: AccountSnapshot | None,
        weekly_loss: Decimal,
        moment: datetime,
    ) -> None:
        if self.risk_lock is None:
            return
        equity = snapshot.equity if snapshot is not None else ZERO
        daily = ZERO
        if snapshot is not None and equity > ZERO and snapshot.daily_pnl < ZERO:
            daily = min(Decimal("1"), (-snapshot.daily_pnl) / equity)
        drawdown = snapshot.drawdown_fraction if snapshot is not None else ZERO
        self.risk_lock.evaluate(
            daily_loss=daily,
            weekly_loss=weekly_loss,
            drawdown=drawdown,
            kill_switch_active=self.killswitch.is_active(),
            now=moment,
        )

    def _effective_policy(self, risk_fraction: Decimal | None):
        """ریسک هر معامله فاز جاری را اعمال می‌کند، اما هرگز از سقف سخت سیاست عبور نمی‌کند."""
        policy = self.settings.risk
        if risk_fraction is None:
            return policy
        try:
            fraction = to_decimal(risk_fraction)
        except (TypeError, ValueError):
            return policy
        if fraction <= ZERO:
            return policy
        return replace(policy, risk_per_trade=min(fraction, policy.hard_cap_risk_per_trade))

    def _with_persisted_peak(self, snapshot: AccountSnapshot | None) -> AccountSnapshot | None:
        """سقف سرمایه تاریخی را از آخرین Snapshot حفظ می‌کند تا Drawdown واقعی باشد."""
        if snapshot is None:
            return None
        previous = self.accounts.latest(snapshot.account_id)
        if previous is None:
            return snapshot
        peak = max(snapshot.peak_equity, previous.peak_equity, snapshot.equity)
        if peak == snapshot.peak_equity:
            return snapshot
        return replace(snapshot, peak_equity=peak)

    def _account(self, account: AccountSnapshot | dict[str, Any] | None, moment: datetime) -> AccountSnapshot | None:
        if account is None:
            return None
        if isinstance(account, AccountSnapshot):
            return account
        return parse_account_snapshot(account, now=moment)

    def _correlations(self, instrument_id: str, other_ids: list[str], timeframe: str, now: datetime) -> dict[str, float]:
        from fxars.core.numerics import correlation

        try:
            base_source = self.instruments.primary_source(instrument_id, timeframe)
        except Exception:
            base_source = None
        base = self.candles.range(instrument_id, timeframe, source_id=base_source,
                                  as_of=now, closed_only=True)
        if len(base) < 30:
            return {}
        base_returns = {
            candle.open_time: float((candle.close - base[index - 1].close) / base[index - 1].close)
            for index, candle in enumerate(base) if index > 0 and base[index - 1].close
        }
        result: dict[str, float] = {}
        window = self.settings.risk.correlation_window
        for other_id in other_ids:
            if other_id == instrument_id:
                result[other_id] = 1.0
                continue
            try:
                other_source = self.instruments.primary_source(other_id, timeframe)
            except Exception:
                other_source = None
            other = self.candles.range(other_id, timeframe, source_id=other_source,
                                       as_of=now, closed_only=True)
            if len(other) < 30:
                result[other_id] = 0.0
                continue
            other_returns = {
                candle.open_time: float((candle.close - other[index - 1].close) / other[index - 1].close)
                for index, candle in enumerate(other) if index > 0 and other[index - 1].close
            }
            aligned = [time for time in base_returns if time in other_returns][-window:]
            if len(aligned) < 10:
                result[other_id] = 0.0
                continue
            result[other_id] = round(correlation([base_returns[time] for time in aligned],
                                                 [other_returns[time] for time in aligned]), 4)
        return result

# FIX-08-WEEKLY-LOSS-FALLBACK
