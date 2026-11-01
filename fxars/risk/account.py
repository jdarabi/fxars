"""تبدیل payload حساب به AccountSnapshot برای API و CLI."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fxars.core.ids import new_id
from fxars.core.numerics import to_decimal
from fxars.core.timeutil import parse_ts, utcnow
from fxars.domain.enums import Side
from fxars.domain.models import AccountSnapshot, Position


def parse_account_snapshot(data: dict[str, Any], *, now: datetime | None = None) -> AccountSnapshot:
    moment = parse_ts(data["taken_at"]) if data.get("taken_at") else (now or utcnow())
    positions = tuple(
        Position(
            position_id=item.get("position_id") or new_id("pos"),
            instrument_id=item["instrument_id"],
            side=Side(item.get("side", "BUY")),
            volume=to_decimal(item["volume"]),
            entry_price=to_decimal(item["entry_price"]),
            current_price=to_decimal(item.get("current_price") or item["entry_price"]),
            stop_loss=to_decimal(item["stop_loss"]) if item.get("stop_loss") else None,
            take_profit=to_decimal(item["take_profit"]) if item.get("take_profit") else None,
            swap=to_decimal(item.get("swap", "0")),
            commission=to_decimal(item.get("commission", "0")),
        )
        for item in data.get("positions", [])
    )
    equity = to_decimal(data["equity"])
    return AccountSnapshot(
        snapshot_id=data.get("snapshot_id") or new_id("acc"),
        account_id=data.get("account_id", "demo-account"),
        currency=data.get("currency", "USD"),
        balance=to_decimal(data.get("balance", data["equity"])),
        equity=equity,
        free_margin=to_decimal(data.get("free_margin", equity)),
        margin_used=to_decimal(data.get("margin_used", "0")),
        peak_equity=to_decimal(data.get("peak_equity", equity)),
        daily_pnl=to_decimal(data.get("daily_pnl", "0")),
        leverage=to_decimal(data.get("leverage", "100")),
        open_positions=int(data.get("open_positions", len(positions))),
        taken_at=moment,
        positions=positions,
        max_daily_loss=to_decimal(data["max_daily_loss"]) if data.get("max_daily_loss") else None,
        max_drawdown=to_decimal(data["max_drawdown"]) if data.get("max_drawdown") else None,
    )


def demo_account(equity: str = "10000", *, now: datetime | None = None, open_positions: int = 0,
                 daily_pnl: str = "0", peak_equity: str | None = None) -> dict[str, Any]:
    moment = now or utcnow()
    value = Decimal(equity)
    peak = Decimal(peak_equity) if peak_equity else value
    return {
        "account_id": "demo-account",
        "currency": "USD",
        "balance": str(value),
        "equity": str(value),
        "free_margin": str(value),
        "margin_used": "0",
        "peak_equity": str(peak),
        "daily_pnl": str(daily_pnl),
        "leverage": "100",
        "open_positions": open_positions,
        "taken_at": moment.isoformat(),
        "positions": [],
    }
