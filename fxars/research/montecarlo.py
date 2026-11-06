"""Monte Carlo روی ترتیب معاملات و تنش هزینه‌ها."""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Any

from fxars.core.numerics import mean, percentile
from fxars.research.metrics import compute_metrics


def monte_carlo_trades(
    trades: Sequence[dict[str, Any]],
    *,
    initial_equity: float,
    runs: int = 500,
    seed: int = 7,
    cost_stress: float = 1.0,
    timeframe: str = "H1",
) -> dict[str, Any]:
    """بازنمونه‌گیری با جایگذاری از توزیع تجربی معاملات + تنش هزینه."""
    if not trades:
        return {"runs": 0, "net_profit": {}, "max_drawdown": {}, "probability_of_loss": None}
    rng = random.Random(seed)
    rng_sequence = random.Random(seed + 1)
    net_profits: list[float] = []
    drawdowns: list[float] = []
    profit_factors: list[float] = []
    pnls = [float(trade["pnl"]) for trade in trades]

    for _ in range(runs):
        sample = [pnls[rng.randrange(len(pnls))] for _ in range(len(pnls))]
        extra_costs = [
            (float(trade.get("commission", 0.0)) + float(trade.get("slippage_cost", 0.0))) * (cost_stress - 1.0)
            for trade in (trades[rng_sequence.randrange(len(trades))] for _ in range(len(trades)))
        ]
        adjusted = [pnl - cost for pnl, cost in zip(sample, extra_costs, strict=False)]
        equity = initial_equity
        peak = initial_equity
        max_dd = 0.0
        curve = [(0, initial_equity)]
        for index, value in enumerate(adjusted, start=1):
            equity += value
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0.0)
            curve.append((index, equity))
        net_profits.append(equity - initial_equity)
        drawdowns.append(max_dd)
        metrics = compute_metrics(
            [{"pnl": value} for value in adjusted],
            [(str(index), value) for index, value in curve],
            initial_equity=initial_equity,
            timeframe=timeframe,
        )
        if metrics["profit_factor"] is not None:
            profit_factors.append(metrics["profit_factor"])

    return {
        "runs": runs,
        "seed": seed,
        "cost_stress": cost_stress,
        "net_profit": {
            "p05": round(percentile(net_profits, 5), 2),
            "p50": round(percentile(net_profits, 50), 2),
            "p95": round(percentile(net_profits, 95), 2),
            "mean": round(mean(net_profits), 2),
        },
        "max_drawdown_pct": {
            "p05": round(percentile(drawdowns, 5) * 100, 4),
            "p50": round(percentile(drawdowns, 50) * 100, 4),
            "p95": round(percentile(drawdowns, 95) * 100, 4),
        },
        "profit_factor_p50": round(percentile(profit_factors, 50), 4) if profit_factors else None,
        "probability_of_loss": round(sum(1 for value in net_profits if value < 0) / runs, 4),
        "worst_net_profit": round(min(net_profits), 2),
        "best_net_profit": round(max(net_profits), 2),
    }
