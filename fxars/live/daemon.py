"""Live daemon: تحلیل real-time، اعلان، و اجرای سفارش با سقف‌های سخت.

اجرای سفارش فقط با سه شرط هم‌زمان فعال می‌شود: پرچم صریح ``execute_orders``،
فاز DEMO/AUTOMATED_LIMITED، و اتصال واقعی MT5. در غیر این صورت daemon فقط
تحلیل/اعلان می‌کند تا هیچ پرکردن ساختگی (paper) در مسیر live ثبت نشود.

FIX-SCENARIO-REFRESH: در ``_execute`` سناریو یک بار دیگر (تا دو تلاش) ارزیابی
می‌شود تا اگر بین ``run_once`` و لحظه اجرا وضعیت WATCH→ARMED→TRIGGERED تغییر
کرده باشد، RiskGate با وضعیت به‌روز تصمیم بگیرد. اگر
``require_triggered_scenario=false`` باشد (فقط دمو)، ARMED/WATCH هم مجاز است.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fxars.core.numerics import ZERO
from fxars.core.timeutil import format_ts
from fxars.domain.enums import Phase, ScenarioStatus, Side
from fxars.live.config import ScheduleConfig

logger = logging.getLogger("fxars.live.daemon")


@dataclass
class LiveDaemonConfig:
    instrument_id: str = "EURUSD"
    instruments: list[str] = field(default_factory=list)
    timeframe: str = "H1"
    timeframes: list[str] = field(default_factory=list)
    interval_seconds: int = 60
    history_bars: int = 500
    source_id: str = "mt5"
    log_path: str = "data/live/daemon.jsonl"
    min_score_threshold: float = 0.15
    send_no_trade: bool = False
    max_signals_per_hour: int = 3
    schedule: ScheduleConfig | None = None
    execute_orders: bool = False  # پیش‌فرض: مشاوره، بدون ارسال سفارش
    account_equity: str = "100"
    reload_phase: bool = False  # هم‌گام‌سازی فاز با config/phase.json در هر چرخه

    @property
    def effective_instruments(self) -> list[str]:
        if self.instruments:
            return [s.upper().strip() for s in self.instruments if s and s.strip()]
        return [self.instrument_id.upper().strip()] if self.instrument_id else ["EURUSD"]

    @property
    def effective_timeframes(self) -> list[str]:
        if self.timeframes:
            return [t.upper().strip() for t in self.timeframes if t and t.strip()]
        return [self.timeframe.upper().strip()] if self.timeframe else ["H1"]

    @classmethod
    def from_live_config(cls, live, *, log_path="data/live/daemon.jsonl"):
        return cls(
            instrument_id=live.instrument,
            instruments=list(getattr(live, "instruments", []) or []),
            timeframe=live.primary_timeframe,
            timeframes=list(live.timeframes) or [live.primary_timeframe],
            interval_seconds=live.interval_seconds,
            history_bars=live.history_bars,
            source_id=live.source_id,
            log_path=log_path,
            send_no_trade=live.send_no_trade,
            max_signals_per_hour=live.max_signals_per_hour,
            min_score_threshold=getattr(live, "min_score_threshold", 0.15),
            schedule=live.schedule,
            execute_orders=bool(getattr(live, "execute_orders", False)),
        )


@dataclass
class LiveDaemonStats:
    cycles: int = 0
    candles_ingested: int = 0
    signals_sent: int = 0
    signals_detected: int = 0
    orders_sent: int = 0
    orders_blocked: int = 0
    risk_rejections: int = 0
    errors: int = 0
    skipped_by_schedule: int = 0
    skipped_below_threshold: int = 0
    last_run_id: str = ""
    last_decision: str = ""
    last_candle_time: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def to_dict(self) -> dict:
        return {
            "cycles": self.cycles,
            "candles_ingested": self.candles_ingested,
            "signals_sent": self.signals_sent,
            "signals_detected": self.signals_detected,
            "orders_sent": self.orders_sent,
            "orders_blocked": self.orders_blocked,
            "risk_rejections": self.risk_rejections,
            "errors": self.errors,
            "skipped_by_schedule": self.skipped_by_schedule,
            "skipped_below_threshold": self.skipped_below_threshold,
            "last_run_id": self.last_run_id,
            "last_decision": self.last_decision,
            "last_candle_time": self.last_candle_time,
            "started_at": format_ts(self.started_at),
            "uptime_seconds": int((datetime.now(tz=UTC) - self.started_at).total_seconds()),
        }


class LiveDaemon:
    def __init__(
        self,
        *,
        config: LiveDaemonConfig,
        platform: Any,
        feed: Any,
        notifier: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.platform = platform
        self.feed = feed
        self.notifier = notifier
        self._sleep = sleep_fn
        self._now = now_fn or (lambda: datetime.now(tz=UTC))
        self._stop = False
        self.stats = LiveDaemonStats()
        self._last_candle_times: dict[tuple[str, str], datetime] = {}
        self._signal_times: list[datetime] = []
        self._last_signal_by_key: dict[tuple[str, str], str] = {}
        self._log_path = Path(config.log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def stop(self) -> None:
        self._stop = True
        logger.info("daemon stop requested")

    def _log_event(self, event: dict[str, Any]) -> None:
        event.setdefault("ts", format_ts(self._now()))
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            logger.warning("log write failed: %s", exc)

    def _schedule_allows(self) -> bool:
        if self.config.schedule is None:
            return True
        return self.config.schedule.should_run(self._now())

    def _can_send_signal(self) -> bool:
        cutoff = self._now() - timedelta(hours=1)
        self._signal_times = [t for t in self._signal_times if t > cutoff]
        return len(self._signal_times) < self.config.max_signals_per_hour

    def _ingest_new(self, instrument: str, tf: str) -> int:
        key = (instrument, tf)
        since = self._last_candle_times.get(key)
        try:
            if since is None:
                candles = self.feed.fetch_recent(instrument, tf, count=self.config.history_bars)
            else:
                candles = self.feed.fetch_new(instrument, tf, since=since, count=100)
        except Exception as exc:
            logger.warning("fetch failed %s/%s: %s", instrument, tf, exc)
            self.stats.errors += 1
            return 0
        if not candles:
            return 0
        try:
            result = self.platform.ingestion.ingest(
                candles, instrument_id=instrument,
                source_id=self.config.source_id, now=self._now(),
            )
        except Exception as exc:
            logger.exception("ingest failed %s/%s: %s", instrument, tf, exc)
            self.stats.errors += 1
            return 0
        self._last_candle_times[key] = candles[-1].open_time
        self._log_event({
            "event": "ingest", "instrument": instrument, "timeframe": tf,
            "accepted": result.accepted, "quarantined": result.quarantined,
            "latest_candle": format_ts(candles[-1].open_time),
        })
        return result.accepted

    def _analyze(self, instrument: str, tf: str) -> Any:
        return self.platform.run_analysis(instrument, tf, actor="live-daemon")

    # ------------------------------------------------------------------ حساب/نرخ
    def _automated_settings(self) -> Any | None:
        phase_settings = getattr(self.platform, "phase_settings", None)
        return getattr(phase_settings, "automated_limited", None)

    def _broker_is_real(self) -> bool:
        broker = getattr(getattr(self.platform, "execution", None), "broker", None)
        return broker is not None and getattr(broker, "name", "") == "mt5"

    def _day_start(self, moment: datetime) -> datetime:
        """آغاز روز معاملاتی (۱۷:۰۰ نیویورک) برای شمارش سهمیه و سود روزانه."""
        calendar = getattr(self.platform, "calendar", None)
        if calendar is not None and hasattr(calendar, "trading_day_start"):
            try:
                return calendar.trading_day_start(moment)
            except Exception:
                pass
        # FIX: fallback دقیق‌تر به trading_date (روز معاملاتی)، نه نیمه‌شب UTC
        if calendar is not None and hasattr(calendar, "trading_date"):
            try:
                trading_day = calendar.trading_date(moment)
                return datetime(
                    trading_day.year, trading_day.month, trading_day.day,
                    hour=17, minute=0, second=0, microsecond=0, tzinfo=UTC,
                ) - timedelta(days=1)
            except Exception:
                pass
        return moment.replace(hour=0, minute=0, second=0, microsecond=0)

    def _trades_today(self) -> int | None:
        orders = getattr(self.platform, "orders", None)
        if orders is None:
            return None
        day_start = self._day_start(self._now())
        try:
            return orders.count_intents_since(day_start)
        except Exception:
            logger.exception("trade count failed")
            return None

    def _lookup_rate(self, quote: str, account_currency: str) -> Decimal | None:
        """نرخ quote→account از جفت مستقیم یا معکوس؛ None یعنی ناموجود."""
        for pair, direct in ((f"{quote}{account_currency}", True),
                             (f"{account_currency}{quote}", False)):
            try:
                tick = self.feed.tick(pair)
            except Exception:
                continue
            if tick is None:
                continue
            mid = (tick["bid"] + tick["ask"]) / Decimal("2")
            if mid <= ZERO:
                continue
            return mid if direct else Decimal("1") / mid
        return None

    def _compute_rates(self, instrument_ids: Iterable[str]) -> tuple[dict[str, Decimal], list[str]]:
        """نرخ تبدیل ارز مظنه هر نماد به ارز حساب؛ ارز بدون نرخ گزارش می‌شود."""
        account_currency = str(self.feed.account_snapshot()["currency"]).upper()
        rates: dict[str, Decimal] = {account_currency: Decimal("1")}
        missing: set[str] = set()
        for instrument_id in {item.upper() for item in instrument_ids if item}:
            try:
                info = self.feed.symbol_info(instrument_id)
            except Exception:
                info = None
            if info is None:
                missing.add(instrument_id)
                continue
            quote = str(info.get("currency_profit") or "").upper()
            if not quote:
                missing.add(instrument_id)
                continue
            if quote in rates:
                continue
            rate = self._lookup_rate(quote, account_currency)
            if rate is None:
                missing.add(quote)
            else:
                rates[quote] = rate
        return rates, sorted(missing)

    def _build_account_from_mt5(self, automated: Any | None = None):
        """ساخت AccountSnapshot با Peak/Daily PnL صحیح و پوزیشن‌های واقعی."""
        from fxars.domain.models import AccountSnapshot, Position

        info = self.feed.account_snapshot()
        now = self.platform.clock()
        raw_positions = self.feed.open_positions()
        positions = tuple(
            Position(
                position_id=item["ticket"],
                instrument_id=item["symbol"],
                side=Side.BUY if int(item["type"]) == 0 else Side.SELL,
                volume=item["volume"],
                entry_price=item["price_open"],
                current_price=item["price_current"],
                stop_loss=item["sl"],
                take_profit=item["tp"],
                commission=item["commission"],
                swap=item["swap"],
            )
            for item in raw_positions
        )
        equity = info["equity"]
        balance = info["balance"]
        day_start = self._day_start(now)
        # نبود تاریخچه معاملات یعنی نمی‌توان زیان روزانه را سنجید ⇒ اجرا متوقف می‌شود.
        realized = self.feed.realized_pnl_since(day_start)
        floating = equity - balance
        daily_pnl = realized + floating

        account_id = str(info["login"])
        previous = None
        accounts = getattr(self.platform, "accounts", None)
        if accounts is not None:
            previous = accounts.latest(account_id)
        peak_candidates = [equity, balance]
        if previous is not None:
            peak_candidates.extend([previous.peak_equity, previous.equity])
        peak_equity = max(peak_candidates)

        max_daily_loss = None
        max_drawdown = None
        if automated is not None and self.platform.settings.phase is Phase.AUTOMATED_LIMITED:
            max_daily_loss = automated.daily_loss_limit
            max_drawdown = automated.drawdown_stop

        return AccountSnapshot(
            snapshot_id=f"acc-mt5-{account_id}-{format_ts(now)}",
            account_id=account_id,
            currency=str(info["currency"]).upper(),
            balance=balance,
            equity=equity,
            free_margin=info["margin_free"],
            margin_used=info["margin_used"],
            peak_equity=peak_equity,
            daily_pnl=daily_pnl,
            leverage=info["leverage"],
            open_positions=len(positions),
            taken_at=now,
            positions=positions,
            max_daily_loss=max_daily_loss,
            max_drawdown=max_drawdown,
        )

    # ------------------------------------------------------------------ اجرا
    def _execution_block_reason(
        self,
        *,
        instrument: str,
        timeframe: str,
        account: Any,
        decision: Any,
        scenario: Any,
        automated: Any | None,
        tick: dict[str, Decimal],
        symbol_info: dict[str, Any],
    ) -> str | None:
        if not self.config.execute_orders:
            return "EXECUTE_DISABLED"
        phase = self.platform.settings.phase
        if phase not in (Phase.DEMO, Phase.AUTOMATED_LIMITED):
            return f"PHASE_{phase.value}"
        if not self.platform.settings.execution_enabled:
            return "EXECUTION_DISABLED"
        # FIX: kill switch به‌صورت واقعی خوانده می‌شود (نه مقدار سخت‌کد‌شده).
        # _execute هم قبلاً این را چک کرده، اما این‌جا هم برای اطمینان و
        # برای اینکه اجرای مستقیم _execution_block_reason (مثلاً در تست) امن بماند.
        killswitch_active = self.platform.killswitch.is_active()
        if killswitch_active:
            return "KILL_SWITCH_ACTIVE"
        if not self._broker_is_real():
            return "REAL_BROKER_UNAVAILABLE"
        if decision.position_size <= ZERO:
            return "POSITION_SIZE_ZERO"

        point = Decimal(str(symbol_info.get("point") or "0"))
        if point <= ZERO:
            return "SYMBOL_POINT_INVALID"
        pip = point * 10 if int(symbol_info.get("digits") or 0) in (3, 5) else point
        spread_pips = (tick["ask"] - tick["bid"]) / pip
        max_spread = self.platform.settings.risk.max_spread_pips
        if automated is not None and phase is Phase.AUTOMATED_LIMITED:
            max_spread = min(max_spread, automated.max_spread_pips)

        from fxars.risk.limits import ExecutionLimitInput, execution_block_reason
        return execution_block_reason(
            ExecutionLimitInput(
                phase=phase,
                execute_orders=self.config.execute_orders,
                execution_enabled=self.platform.settings.execution_enabled,
                killswitch_active=killswitch_active,
                broker_is_real=True,
                position_size=decision.position_size,
                automated=automated,
                instrument=instrument,
                timeframe=timeframe,
                scenario_status=scenario.status if scenario is not None else None,
                spread_pips=spread_pips,
                max_spread_pips=max_spread,
                open_positions=account.open_positions,
                trades_today=self._trades_today(),
            )
        )

    def _execute(self, instrument: str, tf: str, result: Any) -> bool:
        if not self.config.execute_orders:
            return False
        if result.scenario is None:
            return False
        phase = self.platform.settings.phase
        if phase not in (Phase.DEMO, Phase.AUTOMATED_LIMITED):
            logger.info("execute skipped: phase=%s", phase.value)
            return False
        if self.platform.killswitch.is_active():
            logger.warning("execute skipped: kill switch active")
            return False

        automated = self._automated_settings()

        # FIX-SCENARIO-REFRESH: یک بار دیگر سناریو را ارزیابی کن (WATCH→ARMED→TRIGGERED)
        # تا اگر بین run_once و _execute وضعیت تغییر کرده، به‌روز شود.
        try:
            for _attempt in range(2):
                evaluation = self.platform.evaluate_scenario(result.scenario.scenario_id)
                result.scenario = evaluation.scenario
                if evaluation.transition is not None:
                    logger.info(
                        "scenario %s [%d]: %s -> %s (%s)",
                        result.scenario.scenario_id, _attempt + 1,
                        evaluation.transition.from_status.value,
                        evaluation.transition.to_status.value,
                        evaluation.reason,
                    )
                if result.scenario.status is ScenarioStatus.TRIGGERED:
                    break
        except Exception as exc:
            logger.warning("evaluate_scenario failed: %s", exc)

        # FIX-SCENARIO-REFRESH: اگر require_triggered_scenario=false و سناریو ARMED است،
        # اجازه بده (فقط برای دمو). در non-demo، require_triggered_scenario باید true باشد.
        if automated is not None and not getattr(automated, "require_triggered_scenario", True):
            if result.scenario.status in (ScenarioStatus.ARMED, ScenarioStatus.WATCH):
                logger.warning(
                    "scenario %s status=%s allowed by require_triggered_scenario=false (DEMO ONLY)",
                    result.scenario.scenario_id, result.scenario.status.value,
                )

        try:
            account = self._build_account_from_mt5(automated)
            instrument_ids = [instrument, *(position.instrument_id for position in account.positions)]
            rates, missing_rates = self._compute_rates(instrument_ids)
            if missing_rates:
                logger.warning("missing conversion rates: %s (risk will reject)", missing_rates)
            risk_decision = self.platform.evaluate_risk(
                result.scenario.scenario_id, account, rates=rates, actor="live-daemon",
            )
        except Exception as exc:
            logger.exception("risk eval failed %s/%s: %s", instrument, tf, exc)
            self.stats.errors += 1
            return False

        logger.info(
            "risk %s/%s: approved=%s reason=%s size=%s lot",
            instrument, tf, risk_decision.approved,
            risk_decision.reason_code.value, risk_decision.position_size,
        )
        if not risk_decision.approved:
            self.stats.risk_rejections += 1
            logger.warning(
                "RISK REJECTED %s/%s reason=%s detail=%s",
                instrument, tf, risk_decision.reason_code.value, risk_decision.reason_detail,
            )
            return False

        try:
            resolved = self.feed.select_symbol(instrument)
            if resolved is None:
                raise RuntimeError(f"symbol_select failed for {instrument}")
            tick = self.feed.tick(instrument)
            symbol_info = self.feed.symbol_info(instrument)
            if tick is None or symbol_info is None:
                raise RuntimeError(f"tick/info missing for {instrument}")
        except Exception as exc:
            logger.exception("price fetch failed: %s", exc)
            self.stats.errors += 1
            return False

        block_reason = self._execution_block_reason(
            instrument=instrument, timeframe=tf, account=account,
            decision=risk_decision, scenario=result.scenario,
            automated=automated, tick=tick, symbol_info=symbol_info,
        )
        if block_reason is not None:
            self.stats.orders_blocked += 1
            logger.warning("ORDER BLOCKED %s/%s: %s", instrument, tf, block_reason)
            self._log_event({
                "event": "order_blocked", "instrument": instrument, "timeframe": tf,
                "reason": block_reason,
                "scenario_status": result.scenario.status.value,
            })
            return False

        try:
            intent = self.platform.execution.create_intent(
                result.scenario.scenario_id, actor="live-daemon",
            )
        except Exception as exc:
            logger.exception("create_intent failed: %s", exc)
            self.stats.errors += 1
            return False

        point = Decimal(str(symbol_info["point"]))
        pip = point * 10 if int(symbol_info["digits"]) in (3, 5) else point
        price = tick["ask"] if intent.side is Side.BUY else tick["bid"]
        try:
            broker_order = self.platform.execution.submit(
                intent.intent_id, price=price, pip_size=pip, actor="live-daemon",
            )
        except Exception as exc:
            logger.exception("submit failed: %s", exc)
            self.stats.errors += 1
            return False

        self.stats.orders_sent += 1
        broker_order_id = getattr(broker_order, "broker_order_id", "?")
        logger.info(
            "ORDER SENT %s/%s %s %s lot | intent=%s broker=%s price=%s sl=%s tp=%s",
            instrument, tf, intent.side.value, risk_decision.position_size,
            intent.intent_id, broker_order_id, price, intent.stop_loss, intent.take_profit,
        )
        self._log_event({
            "event": "order", "instrument": instrument, "timeframe": tf,
            "intent_id": intent.intent_id, "broker_order_id": broker_order_id,
            "side": intent.side.value, "volume": str(risk_decision.position_size),
            "price": str(price),
            "stop_loss": str(intent.stop_loss),
            "take_profit": str(intent.take_profit) if intent.take_profit else None,
        })
        return True

    def _maybe_notify(self, result: Any, instrument: str, tf: str) -> None:
        decision = result.decision
        action = decision.action.value
        key = (instrument, tf)
        if action == "NO_TRADE":
            if self.config.send_no_trade and self.notifier is not None:
                self.notifier.send_no_trade(result.run.run_id, decision.no_trade_reason or "")
            return

        try:
            score = float(decision.score)
        except (TypeError, ValueError):
            score = 0.0
        if abs(score) < float(self.config.min_score_threshold):
            self.stats.skipped_below_threshold += 1
            logger.info(
                "signal below min_score_threshold: %s/%s score=%.3f threshold=%.3f",
                instrument, tf, score, self.config.min_score_threshold,
            )
            return

        self.stats.signals_detected += 1
        scenario = result.scenario
        entry = scenario.entry_condition.get("level") if scenario and scenario.entry_condition else "?"
        stop = scenario.stop_logic.get("level") if scenario and scenario.stop_logic else "?"
        targets = [t.get("price") for t in (scenario.target_logic or ())] if scenario else []
        logger.info(
            "SIGNAL %s/%s %s score=%+.3f coverage=%.0f%% stability=%.0f%%",
            instrument, tf, action, score,
            float(decision.coverage) * 100, float(decision.stability) * 100,
        )
        if scenario:
            logger.info(
                "  scenario=%s status=%s entry=%s stop=%s targets=%s expiry=%s",
                scenario.scenario_id, scenario.status.value,
                entry, stop, targets, scenario.expiry_at.isoformat(),
            )

        if not self._can_send_signal():
            logger.info("rate limit: too many signals in last hour (%s/%s)", instrument, tf)
            return
        if self._last_signal_by_key.get(key) == action:
            logger.info("duplicate signal for %s/%s, skipped: %s", instrument, tf, action)
            return
        if self.config.execute_orders and self.platform.settings.execution_enabled:
            if self._execute(instrument, tf, result):
                self._signal_times.append(self._now())
                self._last_signal_by_key[key] = action
            # FIX: اگر _execute شکست خورد، _last_signal_by_key ثبت نمی‌شود
            # تا سیکل بعدی دوباره تلاش شود (retry).
            return
        if self.notifier is None:
            self.stats.signals_sent += 1
            self._signal_times.append(self._now())
            self._last_signal_by_key[key] = action
            return
        try:
            ok = self.notifier.send_signal(decision, scenario)
        except Exception as exc:
            logger.exception("notify failed: %s", exc)
            self.stats.errors += 1
            return
        if ok:
            self.stats.signals_sent += 1
            self._signal_times.append(self._now())
            self._last_signal_by_key[key] = action

    def _promote_draft(self, result: Any) -> None:
        if result.scenario is None or result.scenario.status is not ScenarioStatus.DRAFT:
            return
        try:
            self.platform.scenario_service.transition(
                result.scenario.scenario_id,
                ScenarioStatus.WATCH,
                actor="live-daemon",
                reason="auto-promote DRAFT to WATCH",
            )
            result.scenario = self.platform.scenarios.get(result.scenario.scenario_id)
            logger.info("scenario %s promoted DRAFT -> WATCH", result.scenario.scenario_id)
        except Exception as exc:
            logger.warning("DRAFT -> WATCH failed: %s", exc)

    def _sync_runtime_phase(self) -> None:
        """فاز تغییرکرده از داشبورد/CLI را بدون ری‌استارت در این پروسه اعمال می‌کند."""
        if not getattr(self.config, "reload_phase", False):
            return
        apply_phase = getattr(self.platform, "apply_phase", None)
        if not callable(apply_phase):
            return
        try:
            from fxars.config.settings import PhaseSettings

            disk = PhaseSettings.load(getattr(self.platform, "phase_path", None))
            current = getattr(self.platform, "phase_settings", None)
            current_automated = getattr(current, "automated_limited", None)
            if (
                current is not None
                and disk.mode == getattr(current, "mode", None)
                and current_automated is not None
                and current_automated == disk.automated_limited
            ):
                return
            outcome = apply_phase(
                disk.mode,
                automated_enabled=disk.automated_limited.enabled,
                persist=False,
            )
            logger.info(
                "phase reloaded from disk: mode=%s runtime=%s broker=%s",
                disk.mode, outcome["runtime_phase"], outcome["broker"],
            )
        except Exception as exc:
            logger.warning("phase reload failed: %s", exc)

    def run_once(self) -> bool:
        self.stats.cycles += 1
        self._sync_runtime_phase()
        if not self._schedule_allows():
            self.stats.skipped_by_schedule += 1
            if self.stats.cycles % 30 == 0:
                logger.info("cycle %s: skipped by schedule", self.stats.cycles)
            return False
        sent_signal = False
        instruments = self.config.effective_instruments
        timeframes = self.config.effective_timeframes
        total_pairs = len(instruments) * len(timeframes)
        idx = 0
        for instrument in instruments:
            for tf in timeframes:
                idx += 1
                try:
                    n = self._ingest_new(instrument, tf)
                    self.stats.candles_ingested += n
                    if n == 0 and self._last_candle_times.get((instrument, tf)) is None:
                        logger.warning("skip %s/%s: no candles", instrument, tf)
                        continue
                    result = self._analyze(instrument, tf)
                    self.stats.last_run_id = result.run.run_id
                    self.stats.last_decision = result.decision.action.value
                    self.stats.last_candle_time = format_ts(self._now())
                    logger.info(
                        "cycle %s [%s/%s] %s/%s: candles=%s decision=%s score=%+.3f",
                        self.stats.cycles, idx, total_pairs,
                        instrument, tf, n,
                        result.decision.action.value, result.decision.score,
                    )
                    self._log_event({
                        "event": "analysis", "instrument": instrument, "timeframe": tf,
                        "run_id": result.run.run_id,
                        "decision": result.decision.action.value,
                        "score": float(result.decision.score),
                        "coverage": float(result.decision.coverage),
                        "stability": float(result.decision.stability),
                        "scenario_id": result.scenario.scenario_id if result.scenario else None,
                        "scenario_status": result.scenario.status.value if result.scenario else None,
                        "no_trade_reason": result.decision.no_trade_reason,
                        "scenario_reason": getattr(result, "scenario_reason", None),
                    })

                    self._promote_draft(result)

                    try:
                        for _attempt in range(2):
                            if result.scenario is None:
                                break
                            evaluation = self.platform.evaluate_scenario(result.scenario.scenario_id)
                            result.scenario = evaluation.scenario
                            if evaluation.transition is not None:
                                logger.info(
                                    "scenario %s [%d]: %s -> %s (%s)",
                                    result.scenario.scenario_id, _attempt + 1,
                                    evaluation.transition.from_status.value,
                                    evaluation.transition.to_status.value,
                                    evaluation.reason,
                                )
                            if evaluation.scenario.status is ScenarioStatus.TRIGGERED:
                                break
                    except Exception as exc:
                        logger.warning("evaluate_scenario failed: %s", exc)

                    if result.scenario is not None and result.scenario.status in (
                        ScenarioStatus.INVALIDATED, ScenarioStatus.EXPIRED,
                    ):
                        logger.info(
                            "skip notify %s/%s: scenario %s status=%s",
                            instrument, tf, result.scenario.scenario_id,
                            result.scenario.status.value,
                        )
                        continue

                    self._maybe_notify(result, instrument, tf)
                    if result.decision.action.value != "NO_TRADE":
                        sent_signal = True
                except Exception as exc:
                    logger.exception(
                        "cycle %s [%s/%s] %s/%s failed: %s",
                        self.stats.cycles, idx, total_pairs,
                        instrument, tf, exc,
                    )
                    self.stats.errors += 1
                    self._log_event({
                        "event": "error", "instrument": instrument, "timeframe": tf,
                        "error": type(exc).__name__, "message": str(exc),
                    })
        return sent_signal

    def run(self, *, max_cycles: int | None = None) -> None:
        instruments = self.config.effective_instruments
        tfs = self.config.effective_timeframes
        logger.info(
            "daemon starting: %s x %s every %ss (execute_orders=%s)",
            instruments, tfs, self.config.interval_seconds, self.config.execute_orders,
        )
        self._log_event({
            "event": "start", "instruments": instruments, "timeframes": tfs,
            "interval_seconds": self.config.interval_seconds,
            "schedule": self.config.schedule.mode if self.config.schedule else "always",
            "execute_orders": self.config.execute_orders,
            "min_score_threshold": self.config.min_score_threshold,
        })
        try:
            while not self._stop:
                self.run_once()
                if max_cycles is not None and self.stats.cycles >= max_cycles:
                    logger.info("max_cycles=%s reached", max_cycles)
                    break
                for _ in range(self.config.interval_seconds):
                    if self._stop:
                        break
                    self._sleep(1)
        except KeyboardInterrupt:
            logger.info("interrupted")
        finally:
            self._log_event({"event": "stop", "stats": self.stats.to_dict()})
            logger.info("daemon stopped: %s", self.stats.to_dict())
