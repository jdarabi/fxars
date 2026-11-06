"""سرویس ریسک: آماده‌سازی زمینه، اجرای دروازه، ثبت تصمیم و رویداد."""

from __future__ import annotations
from decimal import Decimal

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Callable

from fxars.audit.audit import AuditAction, AuditLog
from fxars.audit.outbox import EventType, Outbox
from fxars.config.settings import Settings
from fxars.core.numerics import to_decimal
from fxars.core.timeutil import utcnow
from fxars.domain.models import AccountSnapshot, RiskDecision
from fxars.instruments.calendar import TradingCalendar
from fxars.risk.account import parse_account_snapshot
from fxars.risk.gate import RiskContext, RiskGate
from fxars.risk.killswitch import KillSwitch
from fxars.storage.repositories import (
    AccountRepository,
    CandleRepository,
    EconomicEventRepository,
    InstrumentRepository,
    RiskRepository,
    ScenarioRepository,
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

    def evaluate(
        self,
        scenario_id: str,
        account: AccountSnapshot | dict[str, Any] | None,
        *,
        rates: dict[str, Any] | None = None,
        now: datetime | None = None,
        actor: str = "system",
    ) -> RiskDecision:
        moment = now or self.clock()
        scenario = self.scenarios.get(scenario_id)
        instrument = self.instruments.find(scenario.instrument_id)
        snapshot = self._account(account, moment)
        candle = None
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
        rate_map = {key: to_decimal(value) for key, value in (rates or {"USD": "1"}).items()}

        # FIX-JPY-RATE: auto-populate quote currency rates from MT5
        if instrument is not None and instrument.quote_currency != (snapshot.currency if snapshot else 'USD'):
            _q = instrument.quote_currency.upper()
            if _q not in rate_map:
                try:
                    import MetaTrader5 as _mt5
                    _mt5.initialize()
                    _acct_ccy = (snapshot.currency if snapshot else 'USD').upper()
                    _pair = f'{_q}{_acct_ccy}'
                    _tick = _mt5.symbol_info_tick(_pair)
                    if _tick is not None and _tick.bid > 0:
                        rate_map[_q] = to_decimal(Decimal('1') / Decimal(str(_tick.bid)))
                    _mt5.shutdown()
                except Exception:
                    pass

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
        )
        decision = self.gate.evaluate(context)

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
