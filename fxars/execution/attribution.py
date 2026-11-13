"""گزارش عملکرد معاملات بسته‌شده و انتساب نتیجه به ابعاد تصمیم."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fxars.core.numerics import ZERO
from fxars.domain.models import ClosedTrade

DIMENSIONS: tuple[str, ...] = (
    "instrument", "side", "timeframe", "regime", "strategy", "scenario", "module",
)


def _dec(value: Decimal) -> str:
    return format(value, "f")


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= ZERO:
        return None
    return numerator / denominator


def summarize(trades: list[ClosedTrade]) -> dict[str, Any]:
    count = len(trades)
    wins = [t for t in trades if t.net_profit > ZERO]
    losses = [t for t in trades if t.net_profit < ZERO]
    flat = count - len(wins) - len(losses)
    net = sum((t.net_profit for t in trades), ZERO)
    gross = sum((t.gross_profit for t in trades), ZERO)
    commission = sum((t.commission for t in trades), ZERO)
    swap = sum((t.swap for t in trades), ZERO)
    win_total = sum((t.net_profit for t in wins), ZERO)
    loss_total = sum((t.net_profit for t in losses), ZERO)
    r_trades = [t for t in trades if t.r_multiple is not None]
    total_r = sum((t.r_multiple for t in r_trades if t.r_multiple is not None), ZERO)
    hold_seconds = [(t.closed_at - t.opened_at).total_seconds() for t in trades]
    profit_factor = _ratio(win_total, abs(loss_total)) if losses else None

    return {
        "trades": count,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": flat,
        "win_rate": round(len(wins) / count, 6) if count else None,
        "net_profit": _dec(net),
        "gross_profit": _dec(gross),
        "commission": _dec(commission),
        "swap": _dec(swap),
        "profit_factor": _dec(profit_factor) if profit_factor is not None else None,
        "expectancy": _dec(net / count) if count else None,
        "average_win": _dec(win_total / len(wins)) if wins else None,
        "average_loss": _dec(loss_total / len(losses)) if losses else None,
        "best_trade": _dec(max(t.net_profit for t in trades)) if trades else None,
        "worst_trade": _dec(min(t.net_profit for t in trades)) if trades else None,
        "r_trades": len(r_trades),
        "total_r": _dec(total_r),
        "average_r": _dec(total_r / len(r_trades)) if r_trades else None,
        "average_hold_seconds": round(sum(hold_seconds) / count, 3) if count else None,
    }


def _key_for(trade: ClosedTrade, dimension: str) -> str:
    if dimension == "instrument":
        return trade.instrument_id
    if dimension == "side":
        return trade.side.value
    if dimension == "timeframe":
        return trade.timeframe or "UNKNOWN"
    if dimension == "regime":
        return trade.regime or "UNKNOWN"
    if dimension == "strategy":
        return trade.strategy or "UNKNOWN"
    if dimension == "scenario":
        return trade.scenario_id or "UNKNOWN"
    raise ValueError(f"dimension نامعتبر: {dimension}")


def group_by(trades: list[ClosedTrade], dimension: str) -> list[dict[str, Any]]:
    if dimension == "module":
        buckets: dict[str, list[ClosedTrade]] = {}
        for trade in trades:
            for module in trade.supporting_modules or ("UNKNOWN",):
                buckets.setdefault(module, []).append(trade)
    else:
        buckets = {}
        for trade in trades:
            buckets.setdefault(_key_for(trade, dimension), []).append(trade)
    rows = [
        {"key": key, "share": round(len(items) / len(trades), 6) if trades else None, **summarize(items)}
        for key, items in buckets.items()
    ]
    rows.sort(key=lambda row: (Decimal(row["net_profit"]), row["trades"]), reverse=True)
    return rows


class AttributionService:
    """گزارش tenant-scoped؛ همه محاسبات از معاملات ذخیره‌شده و نتیجه واقعی بروکر است."""

    def __init__(self, trades) -> None:
        self.trades = trades

    def report(
        self,
        tenant_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        instrument_id: str | None = None,
        dimensions: tuple[str, ...] = DIMENSIONS,
        limit: int = 5000,
    ) -> dict[str, Any]:
        invalid = [name for name in dimensions if name not in DIMENSIONS]
        if invalid:
            raise ValueError(f"dimension نامعتبر: {', '.join(invalid)}")
        items = self.trades.list(
            tenant_id=tenant_id, since=since, until=until,
            instrument_id=instrument_id, limit=limit,
        )
        return {
            "tenant_id": tenant_id,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
            "instrument_id": instrument_id,
            "summary": summarize(items),
            "breakdowns": {name: group_by(items, name) for name in dimensions},
            "trade_count": len(items),
            "truncated": len(items) >= limit,
        }
