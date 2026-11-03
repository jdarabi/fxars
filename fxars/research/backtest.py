"""موتور بک‌تست رویدادمحور با مدل‌سازی اسپرد، کمیسیون، سوآپ و لغزش.

قواعد ضد look-ahead:
* تصمیم فقط با Evidenceهایی گرفته می‌شود که available_at آن‌ها ≤ زمان تصمیم باشد.
* ورود در بازشدن کندل بعد انجام می‌شود.
* اگر در یک کندل هم حد ضرر و هم هدف لمس شود، حد ضرر مقدم است (محافظه‌کارانه).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence

from fxars.config.settings import AnalysisSettings, BacktestSettings
from fxars.core.hashing import sha256_obj
from fxars.core.numerics import ZERO, to_decimal
from fxars.core.timeutil import format_ts, timeframe_delta
from fxars.decision.aggregation import aggregate_evidence
from fxars.domain.enums import DecisionAction, Direction
from fxars.domain.models import Candle, Decision, Evidence, Instrument
from fxars.research.metrics import compute_metrics
from fxars.risk.sizing import SizingInput, calculate_position_size


def _d(value: Any, default: str = "0") -> Decimal:
    return to_decimal(value if value is not None else default)


@dataclass(frozen=True)
class BacktestConfig:
    initial_equity: Decimal = Decimal("10000")
    risk_per_trade: Decimal = Decimal("0.0025")
    spread_pips: Decimal = Decimal("1.2")
    slippage_pips: Decimal = Decimal("0.3")
    commission_per_lot: Decimal = Decimal("7")
    swap_per_lot_per_night: Decimal = Decimal("-2.5")
    stop_buffer_pips: Decimal = Decimal("5")
    target_r_multiples: tuple[Decimal, ...] = (Decimal("1.5"), Decimal("3.0"))
    partial_close_fraction: Decimal = Decimal("0.5")
    breakeven_after_tp1: bool = True
    max_bars_in_trade: int = 24
    expiry_bars: int = 8
    min_signal_strength: float = 0.30
    quote_rates: dict[str, Decimal] = field(default_factory=lambda: {"JPY": Decimal("0.0067")})
    seed: int = 7
    # FIX-05-BACKTEST-PARITY:
    #   "scenario" = منطق دقیقاً هم‌خوان با ScenarioBuilder/TriggerEvaluator
    #   "baseline" = منطق ساده قبلی (stop از کف/سقف ۲۰ کندل + ورود در open)
    mode: str = "scenario"
    # P3-4-ext2: optional regime filter; empty tuple = allow all
    allowed_regimes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "initial_equity", "risk_per_trade", "spread_pips", "slippage_pips",
            "commission_per_lot", "swap_per_lot_per_night", "stop_buffer_pips",
            "partial_close_fraction",
        ):
            object.__setattr__(self, name, _d(getattr(self, name)))
        object.__setattr__(self, "target_r_multiples", tuple(_d(item) for item in self.target_r_multiples))
        object.__setattr__(self, "quote_rates", {key: _d(value) for key, value in self.quote_rates.items()})
        # P3-4-ext2: normalize allowed_regimes to tuple
        if not isinstance(self.allowed_regimes, tuple):
            object.__setattr__(self, "allowed_regimes", tuple(self.allowed_regimes))
        if self.mode not in ("scenario", "baseline"):
            raise ValueError(f"mode نامعتبر: {self.mode!r} (allowed: scenario, baseline)")
        if self.initial_equity <= 0 or not (0 < self.risk_per_trade <= Decimal("0.05")):
            raise ValueError("پارامترهای سرمایه/ریسک بک‌تست نامعتبرند.")

    @classmethod
    def from_settings(
        cls,
        settings: BacktestSettings,
        *,
        overrides: dict[str, Any] | None = None,
        min_signal_strength: float = 0.30,
    ) -> "BacktestConfig":
        base = cls(
            initial_equity=settings.initial_equity,
            risk_per_trade=settings.risk_per_trade,
            spread_pips=settings.default_spread_pips,
            slippage_pips=settings.slippage_pips,
            commission_per_lot=settings.commission_per_lot,
            swap_per_lot_per_night=settings.swap_per_lot_per_night,
            stop_buffer_pips=settings.stop_buffer_pips,
            target_r_multiples=settings.target_r_multiples,
            partial_close_fraction=settings.partial_close_fraction,
            breakeven_after_tp1=settings.breakeven_after_tp1,
            max_bars_in_trade=settings.max_bars_in_trade,
            expiry_bars=settings.expiry_bars,
            min_signal_strength=min_signal_strength,
            quote_rates={"JPY": Decimal("0.0067")},
            seed=settings.seed,
        )
        if overrides:
            values = {field_name: getattr(base, field_name) for field_name in base.__dataclass_fields__}
            for key, value in overrides.items():
                if key not in values:
                    raise ValueError(f"پارامتر ناشناخته بک‌تست: {key}")
                # P3-4-ext2: accept list for allowed_regimes
                if key == "allowed_regimes" and isinstance(value, list):
                    value = tuple(value)
                values[key] = value
            return cls(**values)
        return base

    def to_dict(self) -> dict[str, Any]:
        from fxars.core.serde import jsonable

        return jsonable(self)

    def hash(self) -> str:
        return sha256_obj(self.to_dict())


class EvidenceTimeline:
    """نمایه‌سازی شواهد بر اساس زمان دسترس‌پذیری برای تصمیم‌گیری نقطه‌ای."""

    def __init__(self, evidences: Sequence[Evidence], timeframe: str, *, max_age_bars: int = 6) -> None:
        self.timeframe = timeframe
        self.max_age_bars = max_age_bars
        self._buckets: dict[datetime, list[Evidence]] = {}
        for evidence in evidences:
            self._buckets.setdefault(evidence.available_at, []).append(evidence)
        self._times = sorted(self._buckets)

    def at(self, moment: datetime) -> list[Evidence]:
        cutoff = moment - timeframe_delta(self.timeframe) * self.max_age_bars
        start = bisect.bisect_left(self._times, cutoff)
        end = bisect.bisect_right(self._times, moment)
        result: list[Evidence] = []
        for index in range(start, end):
            result.extend(self._buckets[self._times[index]])
        return result

    @property
    def count(self) -> int:
        return sum(len(items) for items in self._buckets.values())


@dataclass
class _OpenTrade:
    direction: Direction
    entry_index: int
    entry_time: datetime
    entry_price: Decimal
    stop: Decimal
    tp1: Decimal
    tp2: Decimal
    volume: Decimal
    remaining: Decimal
    risk_amount: Decimal
    bars_held: int = 0
    tp1_hit: bool = False
    realized: Decimal = ZERO
    decision_strength: float = 0.0


@dataclass
class BacktestOutput:
    trades: list[dict[str, Any]]
    equity_curve: list[tuple[str, float]]
    metrics: dict[str, Any]
    stats: dict[str, Any]


class BacktestEngine:
    def __init__(
        self,
        instrument: Instrument,
        timeframe: str,
        config: BacktestConfig,
        analysis: AnalysisSettings,
        *,
        calendar=None,
    ) -> None:
        self.instrument = instrument
        self.timeframe = timeframe
        self.config = config
        self.analysis = analysis
        self._pip = instrument.pip_size
        self._contract = instrument.contract_size
        self._quant = Decimal(1).scaleb(-instrument.digits)
        # FIX-06-SWAP: مدت هر کندل به دقیقه، برای محاسبه دقیق Swap
        from fxars.domain.enums import Timeframe as _TF
        self._tf_minutes = _TF.parse(timeframe).minutes
        # FIX-05-BACKTEST-PARITY: builder/evaluator برای حالت scenario
        from fxars.decision.scenario import ScenarioBuilder
        from fxars.decision.trigger import TriggerEvaluator
        if calendar is not None:
            self._scenario_builder = ScenarioBuilder(analysis, calendar)
            self._trigger_evaluator = TriggerEvaluator(analysis, calendar)
        else:
            self._scenario_builder = ScenarioBuilder(analysis)
            self._trigger_evaluator = TriggerEvaluator(analysis)
        # FIX-06-FALLBACK-TRANSPARENT: شمارنده fallback
        self._fallback_count = 0
        self._fallback_errors: dict[str, int] = {}

    def simulate(
        self,
        candles: Sequence[Candle],
        timeline: EvidenceTimeline,
        *,
        start_index: int,
        end_index: int,
        initial_equity: Decimal | None = None,
    ) -> BacktestOutput:
        candles = list(candles)
        if end_index - start_index < 2:
            return BacktestOutput(
                [], [],
                compute_metrics(
                    [], [],
                    initial_equity=float(self.config.initial_equity),
                    timeframe=self.timeframe,
                ),
                {"bars": 0},
            )

        # P3-4-ext2: precompute regime labels once if filter active
        regime_labels: dict[datetime, str] | None = None
        if self.config.allowed_regimes:
            try:
                from fxars.research.regime import classify_regimes

                labels = classify_regimes(candles)
                regime_labels = {c.open_time: lb.regime for c, lb in zip(candles, labels)}
            except Exception:
                regime_labels = None

        equity = initial_equity if initial_equity is not None else self.config.initial_equity
        equity_curve: list[tuple[str, float]] = [
            (format_ts(candles[start_index].open_time), float(equity))
        ]
        trades: list[dict[str, Any]] = []
        position: _OpenTrade | None = None
        pending: dict[str, Any] | None = None
        stats = {
            "bars": 0, "decisions": 0, "entries": 0, "skipped": 0, "no_trade": 0,
            "stops": 0, "targets": 0, "pending_expired": 0, "pending_invalidated": 0,
            "skipped_regime": 0,
            "allowed_regimes": list(self.config.allowed_regimes),
        }

        for index in range(start_index, end_index):
            candle = candles[index]
            stats["bars"] += 1

            # --- pending signal lifecycle
            if position is None and pending is not None:
                mode = pending.get("mode", "baseline")
                if mode == "scenario":
                    pending_expiry = pending.get("expiry_at")
                    if pending_expiry is not None and candle.open_time >= pending_expiry:
                        pending = None
                        stats["pending_expired"] += 1
                    else:
                        stop = pending.get("stop")
                        direction = pending.get("direction")
                        invalidated = False
                        if stop is not None and direction is not None:
                            if direction is Direction.LONG and candle.close <= stop:
                                invalidated = True
                            elif direction is Direction.SHORT and candle.close >= stop:
                                invalidated = True
                        if invalidated:
                            pending = None
                            stats["pending_invalidated"] += 1
                        elif index > pending["created_index"]:
                            position = self._enter(pending, candle, equity)
                            if position is not None:
                                pending = None
                                stats["entries"] += 1
                else:
                    if pending["created_index"] == index - 1:
                        position = self._enter(pending, candle, equity)
                        pending = None
                        if position is not None:
                            stats["entries"] += 1
                    elif pending["created_index"] < index - 1:
                        pending = None

            # --- manage open position
            if position is not None:
                position.bars_held += 1
                result = self._process_bar(position, candle, equity)
                if result is not None:
                    trade, equity = result
                    trades.append(trade)
                    position = None
                    stats["stops" if trade["exit_reason"] in ("STOP_LOSS", "BREAKEVEN") else "targets"] += 1

            # --- decide on new signals
            if position is None and pending is None and index + 1 < end_index:
                decision = self._decide(timeline, candle, regime_labels)
                stats["decisions"] += 1
                if decision is None:
                    # could be no evidence or regime-filtered; check if regime was the cause
                    if regime_labels is not None:
                        regime = regime_labels.get(candle.open_time)
                        if regime is None or regime not in self.config.allowed_regimes:
                            stats["skipped_regime"] += 1
                            continue
                    stats["no_trade"] += 1
                elif decision.action is DecisionAction.NO_TRADE:
                    stats["no_trade"] += 1
                elif decision.strength < self.config.min_signal_strength:
                    stats["skipped"] += 1
                else:
                    if self.config.mode == "scenario":
                        pending = self._plan_from_scenario(decision, candles, index, timeline)
                    else:
                        pending = self._plan(decision, candles, index)

            unrealized = self._mark_to_market(position, candle.close) if position is not None else ZERO
            equity_curve.append((format_ts(candle.open_time), float(equity + unrealized)))

        # --- close any open position at end
        if position is not None:
            last = candles[end_index - 1]
            trade, equity = self._close(position, last.close, "END_OF_DATA", last, equity)
            trades.append(trade)
            equity_curve[-1] = (format_ts(last.open_time), float(equity))

        # FIX-06-FALLBACK-TRANSPARENT: انتقال شمارنده fallback به stats خروجی
        stats["fallback_count"] = self._fallback_count
        stats["fallback_errors"] = dict(self._fallback_errors)
        metrics = compute_metrics(
            trades, equity_curve,
            initial_equity=float(self.config.initial_equity),
            timeframe=self.timeframe,
        )
        stats["skipped_rate"] = round(stats["skipped"] / max(stats["decisions"], 1), 4)
        return BacktestOutput(trades=trades, equity_curve=equity_curve, metrics=metrics, stats=stats)

    # ------------------------------------------------------------------ تصمیم
    def _decide(
        self,
        timeline: EvidenceTimeline,
        candle: Candle,
        regime_labels: dict[datetime, str] | None = None,
    ) -> Decision | None:
        # P3-4-ext2: skip if the current regime is not in the allow-list
        if regime_labels is not None:
            regime = regime_labels.get(candle.open_time)
            if regime is None or regime not in self.config.allowed_regimes:
                return None
        evidences = timeline.at(candle.available_at)
        if not evidences:
            return None
        return aggregate_evidence(evidences, self.analysis, as_of=candle.available_at, timeframe=self.timeframe)

    def _plan(self, decision: Decision, candles: Sequence[Candle], index: int) -> dict[str, Any]:
        # Baseline: stop از کف/سقف ۲۰ کندل + بافر
        window = 20
        start = max(0, index - window + 1)
        if decision.direction is Direction.LONG:
            reference = min(item.low for item in candles[start:index + 1])
            stop = reference - self.config.stop_buffer_pips * self._pip
        else:
            reference = max(item.high for item in candles[start:index + 1])
            stop = reference + self.config.stop_buffer_pips * self._pip
        return {
            "direction": decision.direction,
            "created_index": index,
            "stop": stop.quantize(self._quant),
            "decision_strength": decision.strength,
            "mode": "baseline",
        }

    def _plan_from_scenario(
        self,
        decision: Decision,
        candles: Sequence[Candle],
        index: int,
        timeline: EvidenceTimeline,
    ) -> dict[str, Any] | None:
        # FIX-05-BACKTEST-PARITY: استفاده از همان ScenarioBuilder زنده
        try:
            from fxars.analysis.engine import AnalysisOutcome
            from fxars.analysis.context import IndicatorSet
            window = candles[max(0, index - 600): index + 1]
            indicators = IndicatorSet.build(window, self.analysis)
            # ساخت StructureResult حداقلی برای builder
            from fxars.analysis.structure import StructureResult, Swing
            structure = StructureResult()
            if window:
                highs = max(window[-20:], key=lambda c: c.high)
                lows = min(window[-20:], key=lambda c: c.low)
                structure.last_swing_high = Swing(index=0, price=highs.high, kind="HIGH", confirmed_index=0)
                structure.last_swing_low = Swing(index=0, price=lows.low, kind="LOW", confirmed_index=0)
            outcome = AnalysisOutcome(
                instrument=self.instrument, timeframe=self.timeframe,
                as_of=candles[index].available_at, candles=list(window),
                indicators=indicators, structure=structure,
                evidences=[], summary={}, snapshot_id="bt_inline",
                config_hash=self.config.hash(),
            )
            built = self._scenario_builder.build(
                outcome, decision, run_id="bt_parity", rules_version="rules_v1.3.0",
            )
            if built.scenario is None:
                return None
            sc = built.scenario
            entry_level = Decimal(sc.entry_condition.get("level", "0"))
            stop_level = Decimal(sc.stop_logic.get("level", "0"))
            return {
                "direction": decision.direction,
                "created_index": index,
                "stop": stop_level.quantize(self._quant),
                "entry_trigger": entry_level.quantize(self._quant),
                "targets": list(sc.target_logic),
                "expiry_at": sc.expiry_at,
                "decision_strength": decision.strength,
                "mode": "scenario",
            }
        except Exception as exc:
            # FIX-06-FALLBACK-TRANSPARENT: ثبت علت fallback در stats
            err_name = type(exc).__name__
            self._fallback_count += 1
            self._fallback_errors[err_name] = self._fallback_errors.get(err_name, 0) + 1
            fallback = self._plan(decision, candles, index)
            fallback["mode"] = "baseline_fallback"
            fallback["fallback_error"] = err_name
            return fallback

    # ------------------------------------------------------------------ ورود
    def _enter(self, plan: dict[str, Any], candle: Candle, equity: Decimal) -> _OpenTrade | None:
        direction: Direction = plan["direction"]
        spread = candle.spread if candle.spread is not None else self.config.spread_pips * self._pip
        half = spread / Decimal("2")
        slip = self.config.slippage_pips * self._pip
        entry_trigger = plan.get("entry_trigger")
        if plan.get("mode") == "scenario" and entry_trigger is not None:
            # ورود در Trigger Level اگر در دامنه کندل لمس شده باشد
            if direction is Direction.LONG:
                if candle.high < entry_trigger:
                    return None
                entry = max(candle.open, entry_trigger) + half + slip
            else:
                if candle.low > entry_trigger:
                    return None
                entry = min(candle.open, entry_trigger) - half - slip
        else:
            if direction is Direction.LONG:
                entry = candle.open + half + slip
            else:
                entry = candle.open - half - slip
        entry = entry.quantize(self._quant)
        stop = plan["stop"]
        distance = abs(entry - stop)
        if distance < Decimal("3") * self._pip or distance > Decimal("150") * self._pip:
            return None
        if direction is Direction.LONG and stop >= entry:
            return None
        if direction is Direction.SHORT and stop <= entry:
            return None
        sizing = calculate_position_size(
            SizingInput(
                equity=equity,
                risk_fraction=self.config.risk_per_trade,
                entry_price=entry,
                stop_price=stop,
                instrument=self.instrument,
                quote_to_account_rate=self._quote_rate(),
                commission_per_lot=self.config.commission_per_lot,
            )
        )
        if not sizing.valid or sizing.volume <= ZERO:
            return None
        sign = 1 if direction is Direction.LONG else -1
        tp1 = (entry + distance * self.config.target_r_multiples[0] * sign).quantize(self._quant)
        tp2 = (entry + distance * self.config.target_r_multiples[-1] * sign).quantize(self._quant)
        return _OpenTrade(
            direction=direction,
            entry_index=plan["created_index"] + 1,
            entry_time=candle.open_time,
            entry_price=entry,
            stop=stop,
            tp1=tp1,
            tp2=tp2,
            volume=sizing.volume,
            remaining=sizing.volume,
            risk_amount=sizing.risk_amount,
            decision_strength=plan.get("decision_strength", 0.0),
        )

    # ------------------------------------------------------------------ مدیریت
    def _process_bar(
        self,
        position: _OpenTrade,
        candle: Candle,
        equity: Decimal,
    ) -> tuple[dict[str, Any], Decimal] | None:
        pip = self._pip
        # FIX-06-GAP-STOP: Gap-aware Stop Loss.
        # اگر کندل با Gap از Stop عبور کند، ضرر واقعی بر اساس قیمت open است، نه stop.
        # این رفتار هم واقع‌گراتر و هم برای تریدر بدبینانه‌تر است.
        if position.direction is Direction.LONG:
            stop_fill = None
            if candle.open < position.stop:
                # Gap Down → خروج در open (بدتر برای LONG)
                stop_fill = candle.open - self.config.slippage_pips * pip
            elif candle.low <= position.stop:
                # داخل کندل به Stop رسیده
                stop_fill = position.stop - self.config.slippage_pips * pip
            if stop_fill is not None:
                return self._close(position, stop_fill, "STOP_LOSS", candle, equity)
            if not position.tp1_hit and candle.high >= position.tp1:
                self._partial(position, position.tp1)
            elif position.tp1_hit and candle.high >= position.tp2:
                return self._close(position, position.tp2, "TARGET_2", candle, equity)
        else:
            stop_fill = None
            if candle.open > position.stop:
                # Gap Up → خروج در open (بدتر برای SHORT)
                stop_fill = candle.open + self.config.slippage_pips * pip
            elif candle.high >= position.stop:
                stop_fill = position.stop + self.config.slippage_pips * pip
            if stop_fill is not None:
                return self._close(position, stop_fill, "STOP_LOSS", candle, equity)
            if not position.tp1_hit and candle.low <= position.tp1:
                self._partial(position, position.tp1)
            elif position.tp1_hit and candle.low <= position.tp2:
                return self._close(position, position.tp2, "TARGET_2", candle, equity)

        if position.bars_held >= self.config.max_bars_in_trade:
            return self._close(position, candle.close, "TIME_EXIT", candle, equity)
        if position.bars_held >= self.config.expiry_bars and not position.tp1_hit:
            return self._close(position, candle.close, "TIME_EXIT", candle, equity)
        return None

    def _partial(self, position: _OpenTrade, price: Decimal) -> None:
        fraction = min(self.config.partial_close_fraction, Decimal("0.9"))
        closed_volume = (position.volume * fraction).quantize(self.instrument.lot_step)
        closed_volume = min(closed_volume, position.remaining)
        if closed_volume < self.instrument.min_lot:
            closed_volume = min(position.remaining, self.instrument.min_lot)
        if closed_volume <= ZERO:
            return
        sign = 1 if position.direction is Direction.LONG else -1
        position.realized += (
            (price - position.entry_price)
            * closed_volume
            * self._contract
            * self._quote_rate()
            * sign
        )
        position.remaining -= closed_volume
        position.tp1_hit = True
        if self.config.breakeven_after_tp1:
            position.stop = position.entry_price

    def _close(
        self,
        position: _OpenTrade,
        price: Decimal,
        reason: str,
        candle: Candle,
        equity: Decimal | None = None,
    ) -> tuple[dict[str, Any], Decimal]:
        rate = self._quote_rate()
        sign = 1 if position.direction is Direction.LONG else -1
        remaining_pnl = (price - position.entry_price) * position.remaining * self._contract * rate * sign
        gross = position.realized + remaining_pnl
        commission = self.config.commission_per_lot * position.volume
        # FIX-06-SWAP: nights = bars * (timeframe_minutes / 1440)
        #   H1 → 1/24 روز به ازای هر کندل
        #   H4 → 4/24 = 1/6 روز
        #   M15 → 15/1440 = 1/96 روز
        minutes_held = Decimal(position.bars_held) * Decimal(self._tf_minutes)
        nights = minutes_held / Decimal("1440")
        swap = self.config.swap_per_lot_per_night * position.volume * nights
        net = gross - commission + swap
        spread = candle.spread if candle.spread is not None else self.config.spread_pips * self._pip
        spread_cost = spread * position.volume * self._contract * rate
        slippage_cost = self.config.slippage_pips * self._pip * position.volume * self._contract * rate * 2
        base_equity = equity if equity is not None else self.config.initial_equity
        current_equity = base_equity + net
        risk_amount = position.risk_amount if position.risk_amount > ZERO else Decimal("1")
        exit_reason = reason
        if reason == "STOP_LOSS" and position.tp1_hit and position.stop == position.entry_price:
            exit_reason = "BREAKEVEN"
        trade = {
            "trade_id": f"bt_{position.entry_time.strftime('%Y%m%d%H%M')}_{position.direction.value}",
            "direction": position.direction.value,
            "entry_time": format_ts(position.entry_time),
            "exit_time": format_ts(candle.open_time),
            "entry_price": format(position.entry_price, "f"),
            "exit_price": format(price, "f"),
            "stop": format(position.stop, "f"),
            "tp1": format(position.tp1, "f"),
            "tp2": format(position.tp2, "f"),
            "volume": format(position.volume, "f"),
            "pnl": round(float(net), 6),
            "pnl_gross": round(float(gross), 6),
            "commission": round(float(commission), 6),
            "swap": round(float(swap), 6),
            "spread_cost": round(float(spread_cost), 6),
            "slippage_cost": round(float(slippage_cost), 6),
            "r_multiple": round(float(net / risk_amount), 4),
            "bars_held": position.bars_held,
            "exit_reason": exit_reason,
            "evidence_strength": round(position.decision_strength, 4),
            "equity_after": round(float(current_equity), 4),
        }
        return trade, current_equity

    def _mark_to_market(self, position: _OpenTrade, price: Decimal) -> Decimal:
        sign = 1 if position.direction is Direction.LONG else -1
        unrealized = (price - position.entry_price) * position.remaining * self._contract * self._quote_rate() * sign
        return position.realized + unrealized

    def _quote_rate(self) -> Decimal:
        if self.instrument.quote_currency.upper() == "USD":
            return Decimal("1")
        return self.config.quote_rates.get(self.instrument.quote_currency, Decimal("1"))


def default_backtest_config(
    settings: BacktestSettings,
    *,
    min_signal_strength: float = 0.30,
    overrides: dict[str, Any] | None = None,
) -> BacktestConfig:
    return BacktestConfig.from_settings(settings, overrides=overrides, min_signal_strength=min_signal_strength)


# FIX-05-ENGINE-DONE
# P3-4-ext2: regime filter support