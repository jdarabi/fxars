"""Walk-forward و تحلیل حساسیت روی شبکه پارامترها."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from fxars.config.settings import Settings
from fxars.core.timeutil import format_ts
from fxars.research.backtest import BacktestConfig, BacktestEngine
from fxars.research.metrics import compute_metrics
from fxars.research.protocol import walk_forward_windows
from fxars.research.service import ResearchService

DEFAULT_GRID: tuple[dict[str, Any], ...] = (
    {"stop_buffer_pips": 3},
    {"stop_buffer_pips": 5},
    {"stop_buffer_pips": 8},
    {"target_r_multiples": [2.0, 4.0]},
    {"min_signal_strength": 0.45},
    {"max_bars_in_trade": 16},
    {"expiry_bars": 6},
)


@dataclass
class WalkForwardResult:
    folds: list[dict[str, Any]]
    aggregate: dict[str, Any]
    grid: list[dict[str, Any]]
    windows: int

    def to_dict(self) -> dict[str, Any]:
        return {"folds": self.folds, "aggregate": self.aggregate, "grid": self.grid, "windows": self.windows}


class WalkForwardRunner:
    def __init__(self, settings: Settings, research: ResearchService) -> None:
        self.settings = settings
        self.research = research

    def run(
        self,
        instrument_id: str,
        timeframe: str,
        *,
        grid: Sequence[dict[str, Any]] | None = None,
        as_of: datetime | None = None,
        min_train_trades: int = 3,
    ) -> WalkForwardResult:
        context = self.research.prepare(instrument_id, timeframe, as_of=as_of)
        variants = list(grid or DEFAULT_GRID)
        windows = walk_forward_windows(
            len(context.candles),
            train_bars=self.settings.backtest.walkforward_train_bars,
            test_bars=self.settings.backtest.walkforward_test_bars,
            step_bars=self.settings.backtest.walkforward_step_bars,
            min_train=self.settings.analysis.min_bars,
        )
        folds: list[dict[str, Any]] = []
        aggregate_trades: list[dict[str, Any]] = []
        aggregate_curve: list[tuple[str, float]] = []
        equity = float(self.settings.backtest.initial_equity)

        for window in windows:
            best: dict[str, Any] | None = None
            for overrides in variants:
                config = BacktestConfig.from_settings(
                    self.settings.backtest, overrides=dict(overrides),
                    min_signal_strength=self.settings.risk.min_signal_strength,
                )
                engine = BacktestEngine(context.instrument, timeframe, config, self.settings.analysis)
                train_output = engine.simulate(
                    context.candles, context.timeline, start_index=window.train_start, end_index=window.train_end,
                )
                trades = train_output.metrics.get("trade_count", 0)
                objective = train_output.metrics.get("net_profit", 0.0) if trades >= min_train_trades else float("-inf")
                if best is None or objective > best["objective"]:
                    best = {
                        "objective": objective, "overrides": overrides, "config": config,
                        "metrics": train_output.metrics,
                    }
            if best is None:
                continue
            engine = BacktestEngine(context.instrument, timeframe, best["config"], self.settings.analysis)
            test_output = engine.simulate(
                context.candles, context.timeline, start_index=window.test_start, end_index=window.test_end,
                initial_equity=Decimal(str(equity)),
            )
            equity += float(test_output.metrics.get("net_profit", 0.0))
            aggregate_trades.extend(test_output.trades)
            for time, value in test_output.equity_curve[1:]:
                aggregate_curve.append((time, float(value)))
            folds.append({
                "fold": window.fold,
                "train": {"start": format_ts(context.candles[window.train_start].open_time),
                          "end": format_ts(context.candles[min(window.train_end, len(context.candles) - 1)].open_time)},
                "test": {"start": format_ts(context.candles[window.test_start].open_time),
                         "end": format_ts(context.candles[min(window.test_end, len(context.candles) - 1)].open_time)},
                "selected": best["overrides"],
                "train_metrics": {key: best["metrics"].get(key) for key in ("net_profit", "trade_count", "profit_factor", "max_drawdown_pct")},
                "test_metrics": {key: test_output.metrics.get(key) for key in ("net_profit", "trade_count", "profit_factor", "max_drawdown_pct", "sharpe")},
            })

        if not aggregate_curve:
            aggregate_curve = [(format_ts(context.candles[0].open_time), float(self.settings.backtest.initial_equity))]
        aggregate = compute_metrics(
            aggregate_trades, aggregate_curve, initial_equity=float(self.settings.backtest.initial_equity), timeframe=timeframe,
        )
        aggregate["folds"] = len(folds)
        aggregate["oos_trade_count"] = len(aggregate_trades)
        return WalkForwardResult(folds=folds, aggregate=aggregate, grid=list(variants), windows=len(windows))

    def sensitivity(
        self,
        instrument_id: str,
        timeframe: str,
        *,
        grid: Sequence[dict[str, Any]] | None = None,
        as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        context = self.research.prepare(instrument_id, timeframe, as_of=as_of)
        results: list[dict[str, Any]] = []
        for overrides in (grid or DEFAULT_GRID):
            config = BacktestConfig.from_settings(
                self.settings.backtest, overrides=dict(overrides),
                min_signal_strength=self.settings.risk.min_signal_strength,
            )
            engine = BacktestEngine(context.instrument, timeframe, config, self.settings.analysis)
            output = engine.simulate(
                context.candles, context.timeline,
                start_index=self.settings.analysis.min_bars, end_index=len(context.candles),
            )
            results.append({
                "overrides": overrides,
                "metrics": {key: output.metrics.get(key) for key in
                            ("net_profit", "trade_count", "profit_factor", "max_drawdown_pct", "sharpe", "expectancy")},
            })
        return results
