"""معیارهای عملکرد و ریسک بک‌تست (بخش ۱۱-۲ و پیوست الف)."""

from __future__ import annotations

import math
from typing import Any, Sequence

from fxars.core.numerics import annualization_factor, mean, percentile, safe_div, stdev


def compute_metrics(
    trades: Sequence[dict[str, Any]],
    equity_curve: Sequence[tuple[str, float]],
    *,
    initial_equity: float,
    timeframe: str,
) -> dict[str, Any]:
    pnls = [float(trade["pnl"]) for trade in trades]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    net_profit = sum(pnls)
    final_equity = float(equity_curve[-1][1]) if equity_curve else initial_equity
    win_rate = safe_div(len(wins), len(pnls))
    avg_win = mean(wins)
    avg_loss = mean(losses)
    profit_factor = None if gross_loss == 0 else abs(gross_profit / gross_loss)

    equities = [float(point[1]) for point in equity_curve] or [initial_equity]
    max_drawdown, max_dd_pct = _drawdown(equities)
    returns = [
        (equities[index] - equities[index - 1]) / equities[index - 1]
        for index in range(1, len(equities))
        if equities[index - 1] > 0
    ]
    periods = annualization_factor(timeframe)
    sharpe = _sharpe(returns, periods)
    sortino = _sortino(returns, periods)
    annual_return = 0.0
    if initial_equity > 0 and equities:
        years = max(len(equities) / periods, 1e-9)
        annual_return = (final_equity / initial_equity) ** (1.0 / years) - 1.0 if final_equity > 0 else -1.0
    calmar = safe_div(annual_return, max_dd_pct)

    costs = {
        "spread": round(sum(float(trade.get("spread_cost", 0.0)) for trade in trades), 6),
        "commission": round(sum(float(trade.get("commission", 0.0)) for trade in trades), 6),
        "swap": round(sum(float(trade.get("swap", 0.0)) for trade in trades), 6),
        "slippage": round(sum(float(trade.get("slippage_cost", 0.0)) for trade in trades), 6),
    }
    costs["total"] = round(sum(costs.values()), 6)

    bars_held = sum(int(trade.get("bars_held", 0)) for trade in trades)
    total_bars = max(len(equities) - 1, 1)
    consecutive = _consecutive(pnls)

    return {
        "net_profit": round(net_profit, 6),
        "return_pct": round(safe_div(net_profit, initial_equity) * 100, 6),
        "final_equity": round(final_equity, 6),
        "gross_profit": round(gross_profit, 6),
        "gross_loss": round(gross_loss, 6),
        "profit_factor": None if profit_factor is None else round(profit_factor, 6),
        "profit_factor_defined": profit_factor is not None,
        "expectancy": round(mean(pnls), 6),
        "win_rate": round(win_rate, 6),
        "win_count": len(wins),
        "loss_count": len(losses),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "payoff_ratio": round(safe_div(avg_win, abs(avg_loss)), 6),
        "max_drawdown": round(max_drawdown, 6),
        "max_drawdown_pct": round(max_dd_pct, 6),
        "sharpe": round(sharpe, 6),
        "sortino": round(sortino, 6),
        "calmar": round(calmar, 6),
        "annualized_return_pct": round(annual_return * 100, 6),
        "trade_count": len(pnls),
        "long_trades": sum(1 for trade in trades if str(trade.get("direction")) == "LONG"),
        "short_trades": sum(1 for trade in trades if str(trade.get("direction")) == "SHORT"),
        "avg_bars_held": round(safe_div(bars_held, len(trades)), 3),
        "exposure_pct": round(safe_div(bars_held, total_bars) * 100, 3),
        "turnover": round(sum(float(trade.get("volume", 0.0)) for trade in trades), 6),
        "avg_r": round(mean([float(trade.get("r_multiple", 0.0)) for trade in trades]), 6),
        "largest_win": round(max(wins), 6) if wins else 0.0,
        "largest_loss": round(min(losses), 6) if losses else 0.0,
        "max_consecutive_wins": consecutive[0],
        "max_consecutive_losses": consecutive[1],
        "costs": costs,
        "bars": total_bars,
    }


def equity_returns(equity_curve: Sequence[tuple[str, float]]) -> list[float]:
    values = [float(point[1]) for point in equity_curve]
    return [
        (values[index] - values[index - 1]) / values[index - 1]
        for index in range(1, len(values))
        if values[index - 1] > 0
    ]


def _sharpe(returns: Sequence[float], periods: float) -> float:
    if len(returns) < 2:
        return 0.0
    sigma = stdev(returns)
    if sigma == 0:
        return 0.0
    return mean(returns) / sigma * math.sqrt(periods)


def _sortino(returns: Sequence[float], periods: float) -> float:
    if len(returns) < 2:
        return 0.0
    downside = [min(value, 0.0) for value in returns]
    downside_dev = math.sqrt(sum(value * value for value in downside) / len(downside))
    if downside_dev == 0:
        return 0.0
    return mean(returns) / downside_dev * math.sqrt(periods)


def _drawdown(equities: Sequence[float]) -> tuple[float, float]:
    peak = equities[0]
    max_dd = 0.0
    max_pct = 0.0
    for value in equities:
        peak = max(peak, value)
        drawdown = peak - value
        if drawdown > max_dd:
            max_dd = drawdown
            max_pct = safe_div(drawdown, peak)
    return max_dd, max_pct


def _consecutive(pnls: Sequence[float]) -> tuple[int, int]:
    best_win = worst_loss = 0
    current_win = current_loss = 0
    for value in pnls:
        if value > 0:
            current_win += 1
            current_loss = 0
        elif value < 0:
            current_loss += 1
            current_win = 0
        best_win = max(best_win, current_win)
        worst_loss = max(worst_loss, current_loss)
    return best_win, worst_loss


def summarize_percentiles(values: Sequence[float]) -> dict[str, float]:
    return {
        "p05": round(percentile(values, 5), 6),
        "p50": round(percentile(values, 50), 6),
        "p95": round(percentile(values, 95), 6),
        "mean": round(mean(values), 6),
    }
