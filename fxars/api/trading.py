"""API endpoints برای معاملات (Trading)، دانلود هیستوری، و انتخاب استراتژی.

FIX-30-MULTI-TRADE:
- GET  /api/v1/trading/status         → وضعیت بروکر/MT5
- GET  /api/v1/orders                 → فهرست سفارشات
- GET  /api/v1/orders/{id}            → جزئیات سفارش
- POST /api/v1/orders                 → ارسال سفارش (فاز غیر READ_ONLY)
- POST /api/v1/trading/reconcile      → تطبیق سفارش‌های UNKNOWN
- POST /api/v1/trading/reconcile-closes → بستن معاملات از هیستوری بروکر
- GET  /api/v1/trading/closed-trades  → فهرست معاملات بسته‌شده با سود/زیان واقعی
- GET  /api/v1/trading/attribution    → گزارش انتساب عملکرد به ابعاد
- POST /api/v1/history/download       → دانلود هیستوری از MT5
- POST /api/v1/history/ingest         → ingest فایل‌های CSV دانلودشده
- GET  /api/v1/history/files          → فهرست فایل‌های موجود
- POST /api/v1/strategy/analyze       → تحلیل استراتژی‌ها روی نماد
- POST /api/v1/strategy/trade         → انتخاب بهترین استراتژی + ارسال سفارش (تک نماد)
- POST /api/v1/strategy/trade_multi   → انتخاب بهترین استراتژی + ارسال سفارش (چند نماد)
"""
from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from fxars.core.errors import (
    NotFoundError,
    PhaseViolationError,
    ValidationError,
)
from fxars.core.logging_setup import get_logger
from fxars.domain.enums import OrderStatus, Permission, Phase, Side

logger = get_logger("api.trading")


def _phase_allows_trading(app):
    """FIX-DUAL: TRADING-LOCKED — در ADVISOR/READ_ONLY هر سفارشی ممنوع است."""
    from fxars.core.errors import PhaseViolationError
    phase = app.platform.settings.phase
    if phase.is_advisor_mode:
        raise PhaseViolationError(
            "ارسال سفارش در فاز مشاور/READ_ONLY مجاز نیست.",
            details={"phase": phase.value},
        )


def _build_account_snapshot(feed: Any, platform: Any):
    """AccountSnapshot از MT5 برای RiskGate (بدون نوشتن در بروکر)."""
    from fxars.domain.models import AccountSnapshot, Position

    info = feed.account_snapshot()
    now = platform.clock()
    positions = tuple(
        Position(
            position_id=item["ticket"],
            instrument_id=item["symbol"],
            side="BUY" if int(item["type"]) == 0 else "SELL",
            volume=item["volume"],
            entry_price=item["price_open"],
            current_price=item["price_current"],
            stop_loss=item["sl"],
            take_profit=item["tp"],
            commission=item["commission"],
            swap=item["swap"],
        )
        for item in feed.open_positions()
    )
    equity = info["equity"]
    balance = info["balance"]
    calendar = getattr(platform, "calendar", None)
    day_start = (
        calendar.trading_day_start(now)
        if calendar is not None and hasattr(calendar, "trading_day_start")
        else now.replace(hour=0, minute=0, second=0, microsecond=0)
    )
    daily_pnl = feed.realized_pnl_since(day_start) + (equity - balance)
    account_id = str(info["login"])
    previous = platform.accounts.latest(account_id)
    peak_candidates = [equity, balance]
    if previous is not None:
        peak_candidates.extend([previous.peak_equity, previous.equity])
    max_daily_loss = None
    max_drawdown = None
    automated = platform.phase_settings.automated_limited
    if platform.settings.phase is Phase.AUTOMATED_LIMITED:
        max_daily_loss = automated.daily_loss_limit
        max_drawdown = automated.drawdown_stop
    return AccountSnapshot(
        snapshot_id=f"acc-api-{account_id}-{now.strftime('%Y%m%d%H%M%S')}",
        account_id=account_id,
        currency=str(info["currency"]).upper(),
        balance=balance,
        equity=equity,
        free_margin=info["margin_free"],
        margin_used=info["margin_used"],
        peak_equity=max(peak_candidates),
        daily_pnl=daily_pnl,
        leverage=info["leverage"],
        open_positions=len(positions),
        taken_at=now,
        positions=positions,
        max_daily_loss=max_daily_loss,
        max_drawdown=max_drawdown,
    )


def _conversion_rates(feed: Any, instrument_id: str, account_currency: str) -> dict[str, Decimal]:
    """نرخ quote→account از جفت مستقیم/معکوس؛ نرخ ناموجود حذف می‌شود تا Gate Fail-Closed کند."""
    rates: dict[str, Decimal] = {account_currency: Decimal("1")}
    info = feed.symbol_info(instrument_id)
    quote = str((info or {}).get("currency_profit") or "").upper()
    if not quote or quote == account_currency:
        return rates
    for pair, direct in ((f"{quote}{account_currency}", True),
                         (f"{account_currency}{quote}", False)):
        tick = feed.tick(pair)
        if tick is None:
            continue
        mid = (tick["bid"] + tick["ask"]) / Decimal("2")
        if mid <= 0:
            continue
        rates[quote] = mid if direct else Decimal("1") / mid
        break
    return rates


def _pip_from_info(si: Any) -> Decimal:
    if isinstance(si, dict):
        point = Decimal(str(si["point"]))
        digits = int(si["digits"])
    else:
        point = Decimal(str(si.point))
        digits = int(si.digits)
    return point * 10 if digits in (3, 5) else point


# نگاشت تایم‌فریم به MT5 constant برای symbol_info
_TF_MAP = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1",
}


def _pip_size_for(si: Any) -> Decimal:
    """محاسبه pip_size از symbol_info بر اساس digits."""
    point = Decimal(str(si.point))
    if si.digits in (3, 5):
        return point * 10
    return point


def _strategy_choice(body: dict[str, Any], timeframe: str) -> str | None:
    """انتخاب دستی استراتژی از درخواست؛ None یعنی انتخاب خودکار."""
    raw = body.get("strategy")
    if raw in (None, "", "AUTO", "auto"):
        return None
    from fxars.live.strategy_selector import REQUIRED_TIMEFRAMES, STRATEGIES

    name = str(raw).strip()
    known = {strategy_name for strategy_name, _ in STRATEGIES}
    if name not in known:
        raise ValidationError(
            f"استراتژی نامعتبر: {name}",
            details={"allowed": sorted(known)},
        )
    required = REQUIRED_TIMEFRAMES.get(name)
    if required and timeframe != required:
        raise ValidationError(
            f"استراتژی {name} فقط روی تایم‌فریم {required} اجرا می‌شود.",
            details={"required_timeframe": required},
        )
    return name


def _trend_candles(feed: Any, instrument_id: str, timeframe: str, bars: int) -> list[Any] | None:
    """کندل‌های H1 برای فیلتر روند؛ فقط وقتی ورودی M5 است.

    اگر دریافت H1 شکست بخورد، خطا بالا می‌رود تا سیگنال بدون فیلتر صادر نشود.
    """
    if timeframe != "M5":
        return None
    from fxars.live.strategy_selector import TREND_TIMEFRAME, trend_history_bars

    return feed.fetch_recent(
        instrument_id, TREND_TIMEFRAME, count=trend_history_bars(bars),
    )


def _get_current_price_and_pip(instrument_id: str, side: str) -> tuple[Decimal, Decimal]:
    """قیمت لحظه‌ای (Ask برای BUY / Bid برای SELL) و pip_size را می‌گیرد."""
    from fxars.live.mt5_feed import MT5Feed
    feed = MT5Feed(source_id="api_price")
    try:
        tick = feed._mt5.symbol_info_tick(instrument_id)
        if tick is None:
            raise ValidationError(f"قیمت برای {instrument_id} موجود نیست")
        si = feed._mt5.symbol_info(instrument_id)
        if si is None:
            raise ValidationError(f"مشخصات {instrument_id} موجود نیست")

        price = Decimal(str(tick.ask)) if side == "BUY" else Decimal(str(tick.bid))
        return price, _pip_size_for(si)
    finally:
        feed.shutdown()


def _latest_price(platform: Any, instrument_id: str) -> tuple[Decimal | None, str | None]:
    """آخرین قیمت بسته از منبع اصلی؛ بدون وابستگی به اتصال بروکر."""
    for timeframe in ("M5", "M15", "H1", "H4", "D1"):
        try:
            source_id = platform.instruments.primary_source(instrument_id, timeframe)
        except Exception:
            continue
        try:
            candle = platform.candles.latest_closed(
                instrument_id, timeframe, source_id=source_id, as_of=platform.clock(),
            )
        except Exception:
            candle = None
        if candle is not None:
            return candle.close, timeframe
    return None, None


def _system_positions(platform: Any, tenant_id: str) -> list[dict[str, Any]]:
    """پوزیشن‌های باز از سوابق execution وقتی بروکر پوزیشن ارائه نمی‌دهد (Paper/READ_ONLY)."""
    intents = platform.orders.list_open_intents(tenant_id)
    positions: list[dict[str, Any]] = []
    for intent in intents:
        try:
            instrument = platform.instruments.get(intent.instrument_id)
        except Exception:
            instrument = None
        order = platform.orders.latest_broker_order(intent.intent_id)
        fills = platform.orders.list_fills(intent.intent_id)

        volume = sum((fill.volume for fill in fills), Decimal("0"))
        if volume <= 0 and order is not None and order.filled_volume > 0:
            volume = order.filled_volume
        if volume <= 0:
            volume = intent.volume

        entry: Decimal | None = None
        if fills and volume > 0:
            entry = sum((fill.price * fill.volume for fill in fills), Decimal("0")) / volume
        elif order is not None and order.average_price is not None:
            entry = order.average_price

        current, price_timeframe = _latest_price(platform, intent.instrument_id)
        profit: Decimal | None = None
        if entry is not None and current is not None and instrument is not None:
            sign = Decimal("1") if intent.side is Side.BUY else Decimal("-1")
            profit = (current - entry) * volume * instrument.contract_size * sign
        commission = sum((fill.commission for fill in fills), Decimal("0"))
        opened_at = fills[0].filled_at if fills else intent.created_at

        positions.append({
            "ticket": intent.intent_id,
            "symbol": intent.instrument_id,
            "instrument_id": intent.instrument_id,
            "type": 0 if intent.side is Side.BUY else 1,
            "side": intent.side.value,
            "volume": volume,
            "price_open": entry,
            "price_current": current,
            "profit": profit,
            "commission": commission,
            "swap": Decimal("0"),
            "stop_loss": intent.stop_loss,
            "take_profit": intent.take_profit,
            "opened_at": opened_at.isoformat(),
            "status": intent.status.value,
            "origin": "system",
            "price_timeframe": price_timeframe,
        })
    return positions


def register_trading_routes(app: Any) -> None:
    """ثبت مسیرهای معاملات، دانلود، و استراتژی در ApiApp."""

    # ===================================================================
    # وضعیت بروکر / MT5
    # ===================================================================
    def _broker_status(request, params, user):
        broker = app.platform.execution.broker
        if broker is None:
            return app._json(200, {
                "connected": False,
                "reason": "broker not configured",
                "phase": app.settings.phase.value,
            })
        try:
            from fxars.live.mt5_feed import MT5Feed
            feed = MT5Feed(source_id="api_check")
            info = feed.account_info()
            feed.shutdown()
            return app._json(200, {
                "connected": True,
                "account": info,
                "phase": app.settings.phase.value,
                "broker": getattr(broker, "name", "unknown"),
            })
        except Exception as exc:
            return app._json(200, {
                "connected": False,
                "reason": str(exc),
                "phase": app.settings.phase.value,
            })

    # ===================================================================
    # فهرست سفارشات
    # ===================================================================
    def _orders_list(request, params, user):
        status_str = request.one("status")
        limit = request.integer("limit", 50, maximum=500)
        if status_str:
            try:
                status = OrderStatus(status_str.upper())
            except ValueError:
                raise ValidationError(f"status نامعتبر: {status_str}")
            intents = app.platform.orders.list_intents_by_status(
                status, limit=limit, tenant_id=user.tenant_id,
            )
        else:
            intents = []
            for st in OrderStatus:
                intents.extend(app.platform.orders.list_intents_by_status(
                    st, limit=limit, tenant_id=user.tenant_id,
                ))
            intents.sort(key=lambda x: x.created_at, reverse=True)
            intents = intents[:limit]
        return app._json(200, {
            "items": [i.to_dict() for i in intents],
            "count": len(intents),
        })

    def _orders_get(request, params, user):
        intent = app.platform.orders.get_intent_for_tenant(params["intent_id"], user.tenant_id)
        if intent is None:
            raise NotFoundError(f"سفارش {params['intent_id']} یافت نشد")
        return app._json(200, {"intent": intent.to_dict()})

    # ===================================================================
    # ارسال سفارش دستی (بر اساس سناریو)
    # ===================================================================
    def _orders_submit(request, params, user):
        _phase_allows_trading(app)  # FIX-DUAL: TRADING-LOCKED
        body = request.json()
        scenario_id = body.get("scenario_id")
        if not scenario_id:
            raise ValidationError("scenario_id الزامی است")

        try:
            intent = app.platform.execution.create_intent(
                scenario_id, actor=user.username, tenant_id=user.tenant_id,
            )
        except PhaseViolationError as exc:
            return app._json(403, exc.to_dict())

        if app.settings.phase is Phase.ASSISTED:
            approval = app.platform.approval_service.request(intent.intent_id, actor=user.username)
            return app._json(202, {
                "intent": intent.to_dict(),
                "approval": approval.to_dict(),
                "message": "سفارش در انتظار تأیید اپراتور دوم است.",
            })

        # قیمت لحظه‌ای
        try:
            price, pip_size = _get_current_price_and_pip(intent.instrument_id, intent.side.value)
        except Exception as exc:
            return app._json(503, {
                "error": {"code": "BROKER_UNAVAILABLE", "message": str(exc)},
            })

        try:
            result = app.platform.execution.submit(
                intent.intent_id, price=price, pip_size=pip_size, actor=user.username,
            )
        except Exception as exc:
            return app._json(422, {
                "error": {"code": "SUBMIT_FAILED", "message": str(exc)},
            })
        return app._json(200, {"intent": result.to_dict()})

    # ===================================================================
    # تأیید چهارچشمی (ASSISTED)
    # ===================================================================
    def _order_approval_get(request, params, user):
        intent = app.platform.orders.get_intent_for_tenant(params["intent_id"], user.tenant_id)
        if intent is None:
            raise NotFoundError(f"درخواست تأیید برای {params['intent_id']} یافت نشد")
        approval = app.platform.approval_service.get(params["intent_id"])
        if approval is None:
            raise NotFoundError(f"درخواست تأیید برای {params['intent_id']} یافت نشد")
        return app._json(200, {"approval": approval.to_dict()})

    def _order_approve(request, params, user):
        body = request.json()
        if app.platform.orders.get_intent_for_tenant(params["intent_id"], user.tenant_id) is None:
            raise NotFoundError(f"سفارش {params['intent_id']} یافت نشد")
        approval = app.platform.approval_service.approve(
            params["intent_id"], approved_by=user.username, reason=str(body.get("reason", "")),
        )
        return app._json(200, {"approval": approval.to_dict()})

    def _order_reject(request, params, user):
        body = request.json()
        reason = str(body.get("reason", "")).strip()
        if not reason:
            raise ValidationError("reason الزامی است")
        if app.platform.orders.get_intent_for_tenant(params["intent_id"], user.tenant_id) is None:
            raise NotFoundError(f"سفارش {params['intent_id']} یافت نشد")
        approval = app.platform.approval_service.reject(
            params["intent_id"], rejected_by=user.username, reason=reason,
        )
        return app._json(200, {"approval": approval.to_dict()})

    def _order_submit_approved(request, params, user):
        _phase_allows_trading(app)  # FIX-DUAL: TRADING-LOCKED
        intent_id = params["intent_id"]
        intent = app.platform.orders.get_intent_for_tenant(intent_id, user.tenant_id)
        if intent is None:
            raise NotFoundError(f"سفارش {intent_id} یافت نشد")
        try:
            price, pip_size = _get_current_price_and_pip(intent.instrument_id, intent.side.value)
        except Exception as exc:
            return app._json(503, {"error": {"code": "BROKER_UNAVAILABLE", "message": str(exc)}})
        try:
            if app.settings.phase is Phase.ASSISTED:
                result = app.platform.strategy_execution.submit_approved(
                    intent_id, price=price, pip_size=pip_size, actor=user.username,
                )
            else:
                result = app.platform.execution.submit(
                    intent_id, price=price, pip_size=pip_size, actor=user.username,
                )
        except PhaseViolationError as exc:
            return app._json(403, exc.to_dict())
        except Exception as exc:
            return app._json(422, {"error": {"code": "SUBMIT_FAILED", "message": str(exc)}})
        return app._json(200, {"intent": result.to_dict()})

    # ===================================================================
    # تطبیق (Reconcile)
    # ===================================================================
    def _reconcile(request, params, user):
        from fxars.execution.reconciliation import ReconciliationService
        svc = ReconciliationService(
            orders=app.platform.orders,
            broker=app.platform.execution.broker,
            audit=app.platform.audit,
            outbox=app.platform.outbox,
            clock=app.platform.clock,
        )
        results = svc.reconcile_all(actor=user.username)
        payload = [
            {
                "intent_id": r.intent_id,
                "from_status": r.from_status.value,
                "to_status": r.to_status.value,
                "reason": r.reason,
            }
            for r in results
        ]
        return app._json(200, {"reconciled": payload, "count": len(payload)})

    # ===================================================================
    # بسته‌شدن معاملات و Attribution
    # ===================================================================
    def _reconcile_closes(request, params, user):
        service = app.platform.close_reconciliation
        if service.broker is not app.platform.execution.broker:
            service.broker = app.platform.execution.broker
        supported = callable(getattr(service.broker, "closed_position", None))
        results = app.platform.reconcile_closed_trades(tenant_id=user.tenant_id, actor=user.username)
        return app._json(200, {
            "supported": supported,
            "broker": getattr(service.broker, "name", None),
            "reconciled": [
                {
                    "intent_id": item.intent_id,
                    "trade_id": item.trade_id,
                    "from_status": item.from_status.value,
                    "to_status": item.to_status.value,
                    "closed_volume": format(item.closed_volume, "f"),
                    "net_profit": format(item.net_profit, "f"),
                    "reason": item.reason,
                }
                for item in results
            ],
            "count": len(results),
        })

    def _closed_trades(request, params, user):
        from fxars.core.timeutil import parse_ts
        from fxars.execution.attribution import summarize

        since_raw = request.one("since")
        until_raw = request.one("until")
        since = parse_ts(since_raw) if since_raw else None
        until = parse_ts(until_raw) if until_raw else None
        instrument_id = request.one("instrument")
        limit = request.integer("limit", 100, maximum=500)
        offset = request.integer("offset", 0, minimum=0, maximum=100000)
        items = app.platform.closed_trades.list(
            tenant_id=user.tenant_id, since=since, until=until,
            instrument_id=instrument_id, limit=limit, offset=offset,
        )
        all_items = app.platform.closed_trades.list(
            tenant_id=user.tenant_id, since=since, until=until,
            instrument_id=instrument_id, limit=5000, offset=0,
        )
        return app._json(200, {
            "items": [item.to_dict() for item in items],
            "count": len(items),
            "summary": summarize(all_items),
        })

    def _attribution(request, params, user):
        from fxars.core.timeutil import parse_ts
        from fxars.execution.attribution import DIMENSIONS

        raw = (request.one("dimension") or "all").strip().lower()
        dimensions = DIMENSIONS if raw == "all" else tuple(
            part.strip() for part in raw.split(",") if part.strip()
        )
        since_raw = request.one("since")
        until_raw = request.one("until")
        report = app.platform.attribution.report(
            user.tenant_id,
            since=parse_ts(since_raw) if since_raw else None,
            until=parse_ts(until_raw) if until_raw else None,
            instrument_id=request.one("instrument"),
            dimensions=dimensions,
        )
        return app._json(200, report)

    # ===================================================================
    # پوزیشن‌ها، بستن و لغو سفارش بروکر
    # ===================================================================
    def _positions_list(request, params, user):
        broker = getattr(app.platform.execution, "broker", None)
        broker_name = getattr(broker, "name", None)
        errors: list[str] = []
        items: list[dict[str, Any]] = []
        source = "none"

        list_positions = getattr(broker, "positions", None)
        broker_ok = callable(list_positions)
        if broker_ok:
            try:
                items = [
                    {key: str(value) if isinstance(value, Decimal) else value for key, value in item.items()}
                    for item in list_positions()
                ]
                source = "broker"
            except Exception as exc:  # بروکر قطع/خطا → نمایش از سوابق سیستم
                broker_ok = False
                errors.append(f"broker positions: {exc}")

        if not broker_ok:
            try:
                items = _system_positions(app.platform, user.tenant_id)
                source = "system"
            except Exception as exc:
                errors.append(f"system positions: {exc}")

        return app._json(200, {
            "positions": items,
            "count": len(items),
            "source": source,
            "broker": broker_name,
            "phase": app.platform.settings.phase.value,
            "errors": errors,
        })

    def _close_position(request, params, user):
        if app.settings.phase.is_advisor_mode:
            raise PhaseViolationError("بستن پوزیشن در فاز مشاور/READ_ONLY مجاز نیست.",
                                      details={"phase": app.settings.phase.value})
        broker = app.platform.execution.broker
        close = getattr(broker, "close_position", None)
        if not callable(close):
            return app._json(503, {"error": {"code": "BROKER_UNAVAILABLE", "message": "بروکر از بستن پوزیشن پشتیبانی نمی‌کند"}})
        body = request.json()
        volume = body.get("volume")
        try:
            order, fills = close(int(params["ticket"]), volume=float(volume) if volume is not None else None)
        except Exception as exc:
            return app._json(422, {"error": {"code": "CLOSE_FAILED", "message": str(exc)}})
        app.platform.orders.save_broker_order(order)
        for fill in fills:
            app.platform.orders.save_fill(fill)
        return app._json(200, {
            "broker_order": order.to_dict(),
            "fills": [fill.to_dict() for fill in fills],
        })

    def _cancel_broker_order(request, params, user):
        if app.settings.phase.is_advisor_mode:
            raise PhaseViolationError("لغو سفارش در فاز مشاور/READ_ONLY مجاز نیست.",
                                      details={"phase": app.settings.phase.value})
        broker = app.platform.execution.broker
        cancel = getattr(broker, "cancel_order", None)
        if not callable(cancel):
            return app._json(503, {"error": {"code": "BROKER_UNAVAILABLE", "message": "بروکر از لغو سفارش پشتیبانی نمی‌کند"}})
        ok = cancel(params["broker_order_id"])
        return app._json(200 if ok else 422, {"canceled": bool(ok), "broker_order_id": params["broker_order_id"]})

    # ===================================================================
    # دانلود هیستوری
    # ===================================================================
    def _history_download(request, params, user):
        body = request.json()
        instruments = body.get("instruments") or []
        timeframes = body.get("timeframes") or []
        bars = int(body.get("bars", 5000))
        if not instruments:
            raise ValidationError("instruments الزامی است")
        if not timeframes:
            raise ValidationError("timeframes الزامی است")
        if bars < 1 or bars > 200000:
            raise ValidationError("bars باید بین ۱ و ۲۰۰۰۰۰ باشد")

        from fxars.live.history import download_history
        output_dir = str(Path(app.settings.data_dir) / "history")
        try:
            result = download_history(
                symbols=instruments,
                timeframes=timeframes,
                bars=bars,
                output_dir=output_dir,
                platform=None,
            )
        except Exception as exc:
            return app._json(503, {
                "error": {"code": "DOWNLOAD_FAILED", "message": str(exc)},
            })
        return app._json(200, result)

    def _history_ingest(request, params, user):
        body = request.json()
        files = body.get("files") or []
        if not files:
            raise ValidationError("files الزامی است")
        results = []
        for f in files:
            try:
                path = Path(f)
                if not path.is_absolute():
                    path = Path(app.settings.data_dir) / "history" / path
                if not path.exists():
                    results.append({"file": str(path), "error": "file not found"})
                    continue
                parts = path.stem.split("_")
                symbol = parts[0]
                tf = parts[1] if len(parts) > 1 else "H1"
                r = app.platform.ingest_csv(
                    path, instrument_id=symbol, timeframe=tf, source_id="mt5",
                )
                results.append({
                    "file": str(path),
                    "accepted": r.accepted,
                    "quarantined": r.quarantined,
                })
            except Exception as exc:
                results.append({"file": f, "error": str(exc)})
        return app._json(200, {"results": results})

    def _history_files(request, params, user):
        history_dir = Path(app.settings.data_dir) / "history"
        if not history_dir.exists():
            return app._json(200, {"files": [], "count": 0, "dir": str(history_dir)})
        files = []
        for p in sorted(history_dir.glob("*.csv")):
            stat = p.stat()
            files.append({
                "name": p.name,
                "path": str(p),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
        return app._json(200, {"files": files, "count": len(files), "dir": str(history_dir)})

    # ===================================================================
    # استراتژی: تحلیل
    # ===================================================================
    def _analyze_strategies(request, params, user):
        body = request.json()
        instrument_id = body.get("instrument_id")
        timeframe = str(body.get("timeframe", "H1")).upper()
        bars = int(body.get("bars", 2000))

        if not instrument_id:
            raise ValidationError("instrument_id الزامی است")
        if timeframe not in _TF_MAP:
            raise ValidationError(
                f"timeframe نامعتبر: {timeframe}",
                details={"allowed": list(_TF_MAP.keys())},
            )
        strategy = _strategy_choice(body, timeframe)
        if bars < 100 or bars > 50000:
            raise ValidationError("bars باید بین ۱۰۰ و ۵۰۰۰۰ باشد")

        from fxars.live.mt5_feed import MT5Feed
        try:
            feed = MT5Feed(source_id="api_strategy")
            try:
                candles = feed.fetch_recent(instrument_id, timeframe, count=bars)
                trend = _trend_candles(feed, instrument_id, timeframe, bars)
            finally:
                feed.shutdown()
        except Exception as exc:
            return app._json(503, {
                "error": {
                    "code": "BROKER_UNAVAILABLE",
                    "message": f"MT5 error: {exc}",
                },
            })

        if len(candles) < 100:
            raise ValidationError(
                f"داده کافی نیست ({len(candles)} کندل، حداقل ۱۰۰)",
                details={"instrument": instrument_id, "timeframe": timeframe},
            )

        instrument = app.platform.instruments.find(instrument_id)
        if instrument is None:
            raise NotFoundError(f"نماد {instrument_id} یافت نشد")

        from fxars.live.strategy_selector import select_best_strategy
        try:
            result = select_best_strategy(
                candles, instrument, strategy=strategy, trend_candles=trend,
            )
        except Exception as exc:
            return app._json(500, {
                "error": {
                    "code": "STRATEGY_FAILED",
                    "message": str(exc),
                },
            })
        return app._json(200, result)

    # ===================================================================
    # استراتژی: ارسال سفارش (تک نماد)
    # ===================================================================
    def _trade_with_strategy(request, params, user):
        _phase_allows_trading(app)  # FIX-DUAL: TRADING-LOCKED
        body = request.json()
        instrument_id = body.get("instrument_id")
        timeframe = str(body.get("timeframe", "H1")).upper()
        bars = int(body.get("bars", 2000))

        if not instrument_id:
            raise ValidationError("instrument_id الزامی است")
        if timeframe not in _TF_MAP:
            raise ValidationError(f"timeframe نامعتبر: {timeframe}")
        strategy = _strategy_choice(body, timeframe)
        if bars < 100 or bars > 50000:
            raise ValidationError("bars باید بین ۱۰۰ و ۵۰۰۰۰ باشد")

        from fxars.live.mt5_feed import MT5Feed
        try:
            feed = MT5Feed(source_id="api_trade")
            try:
                candles = feed.fetch_recent(instrument_id, timeframe, count=bars)
                trend = _trend_candles(feed, instrument_id, timeframe, bars)
            finally:
                feed.shutdown()
        except Exception as exc:
            return app._json(503, {
                "error": {"code": "BROKER_UNAVAILABLE", "message": f"MT5 error: {exc}"},
            })

        if len(candles) < 100:
            raise ValidationError(f"داده کافی نیست ({len(candles)} کندل)")

        instrument = app.platform.instruments.find(instrument_id)
        if instrument is None:
            raise NotFoundError(f"نماد {instrument_id} یافت نشد")

        from fxars.live.strategy_selector import select_best_strategy
        try:
            analysis = select_best_strategy(
                candles, instrument, strategy=strategy, trend_candles=trend,
            )
        except Exception as exc:
            return app._json(500, {"error": {"code": "STRATEGY_FAILED", "message": str(exc)}})

        if analysis.get("signal") == "NO_TRADE":
            return app._json(200, {
                "trade": None,
                "analysis": analysis,
                "message": analysis.get("reason", "سیگنال معتبری نیست"),
            })

        # FIX-31-AUTO-TRADE: آیا باید خودکار ارسال شود؟
        # در ASSISTED تأیید اپراتور دوم همان مرحله تأیید است، پس نیازی به
        # فلگ auto_trade نیست؛ سفارش فقط به وضعیت AWAITING_APPROVAL می‌رود.
        is_auto = getattr(app, "_auto_trade_enabled", False) or app.settings.phase is Phase.ASSISTED
        if not is_auto:
             # در حالت دستی، فقط تحلیل را برمی‌گردانیم تا کاربر تایید کند
             logger.info(
                 "manual signal ready: instrument=%s signal=%s (awaiting confirmation)",
                 instrument_id, analysis["signal"],
             )
             return app._json(200, {
                "trade": None,
                "analysis": analysis,
                "message": f"سیگنال {analysis['signal']} آماده است. برای ارسال، دکمه ارسال سفارش را بزنید.",
                "requires_confirmation": True
             })


        entry = analysis.get("entry")
        stop = analysis.get("stop")

        if entry is None or stop is None:
            return app._json(200, {"trade": None, "analysis": analysis, "message": "entry/stop نامعتبر"})

        if app.settings.phase.is_advisor_mode:
            return app._json(403, {
                "error": {"code": "PHASE_VIOLATION", "message": "ارسال سفارش در فاز READ_ONLY/ADVISOR مجاز نیست"},
                "analysis": analysis,
            })

        feed = None
        try:
            from fxars.live.mt5_feed import MT5Feed
            feed = MT5Feed(source_id="api_trade_exec")
            tick = feed.tick(instrument_id)
            info = feed.symbol_info(instrument_id)
            if tick is None or info is None:
                raise ValidationError(f"قیمت/مشخصات {instrument_id} از بروکر دریافت نشد")
            side = "BUY" if analysis["signal"] == "LONG" else "SELL"
            price = tick["ask"] if side == "BUY" else tick["bid"]
            pip = _pip_from_info(info)
            if pip <= 0:
                raise ValidationError("pip_size نامعتبر است")
            spread_pips = (tick["ask"] - tick["bid"]) / pip
            account = _build_account_snapshot(feed, app.platform)
            rates = _conversion_rates(feed, instrument_id, account.currency)
            outcome = app.platform.strategy_execution.execute(
                instrument_id=instrument_id, timeframe=timeframe, analysis=analysis,
                candle=candles[-1], account=account, price=price, pip_size=pip,
                spread_pips=spread_pips, rates=rates, actor=user.username,
                tenant_id=user.tenant_id,
            )
        except PhaseViolationError as exc:
            return app._json(403, exc.to_dict())
        except Exception as exc:
            return app._json(422, {
                "error": {"code": "TRADE_FAILED", "message": str(exc)},
                "analysis": analysis,
            })
        finally:
            if feed is not None:
                feed.shutdown()

        status = 202 if outcome.status == "AWAITING_APPROVAL" else 200
        return app._json(status, {
            "trade": outcome.to_dict(),
            "analysis": analysis,
            "message": outcome.reason,
        })

    # ===================================================================
    # استراتژی: ارسال سفارش چندگانه (Multi-Trade)
    # ===================================================================
    def _trade_multi_with_strategy(request, params, user):
        _phase_allows_trading(app)  # FIX-DUAL: TRADING-LOCKED
        body = request.json()
        instruments = body.get("instruments") or []
        timeframe = str(body.get("timeframe", "H1")).upper()
        bars = int(body.get("bars", 2000))

        if not instruments:
            raise ValidationError("instruments الزامی است")
        if timeframe not in _TF_MAP:
            raise ValidationError(f"timeframe نامعتبر: {timeframe}")
        strategy = _strategy_choice(body, timeframe)
        if bars < 100 or bars > 50000:
            raise ValidationError("bars باید بین ۱۰۰ و ۵۰۰۰۰ باشد")

        from fxars.live.mt5_feed import MT5Feed
        from fxars.live.strategy_selector import select_best_strategy

        try:
            feed = MT5Feed(source_id="api_multi_trade")
        except Exception as exc:
            return app._json(503, {
                "error": {"code": "BROKER_UNAVAILABLE", "message": str(exc)},
            })

        results = []
        try:
            for inst_id in instruments:
                try:
                    instrument = app.platform.instruments.find(inst_id)
                    if not instrument:
                        results.append({"instrument": inst_id, "status": "ERROR", "message": "نماد یافت نشد"})
                        continue

                    candles = feed.fetch_recent(inst_id, timeframe, count=bars)
                    if len(candles) < 100:
                        results.append({"instrument": inst_id, "status": "ERROR", "message": "داده کافی نیست"})
                        continue

                    trend = _trend_candles(feed, inst_id, timeframe, bars)
                    analysis = select_best_strategy(
                        candles, instrument, strategy=strategy, trend_candles=trend,
                    )
                    signal = str(analysis.get("signal", "NO_TRADE")).upper()
                    if signal not in ("LONG", "SHORT"):
                        results.append({
                            "instrument": inst_id, "status": "NO_TRADE",
                            "message": analysis.get("reason", "سیگنال معتبری نیست"),
                            "analysis": analysis,
                        })
                        continue

                    tick = feed.tick(inst_id)
                    info = feed.symbol_info(inst_id)
                    if tick is None or info is None:
                        raise ValidationError(f"قیمت/مشخصات {inst_id} از بروکر دریافت نشد")
                    price = tick["ask"] if signal == "LONG" else tick["bid"]
                    pip = _pip_from_info(info)
                    if pip <= 0:
                        raise ValidationError("pip_size نامعتبر است")
                    spread_pips = (tick["ask"] - tick["bid"]) / pip
                    account = _build_account_snapshot(feed, app.platform)
                    rates = _conversion_rates(feed, inst_id, account.currency)
                    outcome = app.platform.strategy_execution.execute(
                        instrument_id=inst_id, timeframe=timeframe, analysis=analysis,
                        candle=candles[-1], account=account, price=price, pip_size=pip,
                        spread_pips=spread_pips, rates=rates, actor=user.username,
                        tenant_id=user.tenant_id,
                    )
                    results.append({
                        "instrument": inst_id,
                        "status": outcome.status,
                        "message": outcome.reason,
                        "trade": outcome.to_dict(),
                        "analysis": analysis,
                    })
                except PhaseViolationError as exc:
                    results.append({"instrument": inst_id, "status": "PHASE_VIOLATION", "message": str(exc)})
                except Exception as exc:
                    results.append({"instrument": inst_id, "status": "ERROR", "message": str(exc)})
        finally:
            feed.shutdown()

        return app._json(200, {
            "results": results,
            "count": len(results),
            "phase": app.settings.phase.value,
        })


    # ===================================================================
    # Forward Test (event-time replay برای دروازه فاز ۶)
    # ===================================================================
    def _forward_test(request, params, user):
        from fxars.core.timeutil import parse_ts
        from fxars.live.forward_test import DEFAULT_WARMUP, ForwardTestHarness

        body = request.json()
        instrument_id = str(body.get("instrument_id") or body.get("instrument") or "EURUSD")
        timeframe = str(body.get("timeframe", "H1")).upper()
        if timeframe not in _TF_MAP:
            raise ValidationError(f"timeframe نامعتبر: {timeframe}")
        if app.platform.instruments.find(instrument_id) is None:
            raise NotFoundError(f"نماد {instrument_id} یافت نشد")
        warmup = int(body.get("warmup", DEFAULT_WARMUP))
        step_size = int(body.get("step", body.get("step_size", 1)))
        max_steps = int(body.get("max_steps", 25))
        if not 10 <= warmup <= 20000:
            raise ValidationError("warmup باید بین ۱۰ و ۲۰۰۰۰ باشد")
        if not 1 <= step_size <= 20000:
            raise ValidationError("step باید بین ۱ و ۲۰۰۰۰ باشد")
        if not 1 <= max_steps <= 200:
            raise ValidationError("max_steps باید بین ۱ و ۲۰۰ باشد")
        as_of_raw = body.get("as_of")
        starts_raw = body.get("starts_at")

        report = ForwardTestHarness(
            app.platform, instrument_id, timeframe,
            warmup=warmup, step_size=step_size, tenant_id=user.tenant_id,
        ).run(
            as_of=parse_ts(as_of_raw) if as_of_raw else None,
            starts_at=parse_ts(starts_raw) if starts_raw else None,
            actor=user.username,
            max_steps=max_steps,
        )
        return app._json(200, report.to_dict())

    def _set_auto_trade(request, params, user):
        _phase_allows_trading(app)  # FIX-DUAL: TRADING-LOCKED
        body = request.json()
        enabled = bool(body.get("enabled", False))
        app.settings = replace(app.settings, api=replace(app.settings.api, auto_trade_enabled=enabled))
        # ذخیره در حافظه (سرور)
        app._auto_trade_enabled = enabled
        return app._json(200, {"enabled": enabled})

    def _get_auto_trade(request, params, user):
        enabled = getattr(app, "_auto_trade_enabled", False)
        return app._json(200, {"enabled": enabled})

    # ===================================================================
    # تنظیمات هوشمند معاملات (بر اساس سرمایه)
    # ===================================================================
    def _trading_settings_payload(equity_raw: str | None):
        from fxars.config.trading_defaults import recommend_trading_settings

        equity_source = "query"
        if equity_raw not in (None, ""):
            try:
                equity = Decimal(str(equity_raw))
            except Exception:
                raise ValidationError("پارامتر equity باید عدد باشد.") from None
            if equity <= 0:
                raise ValidationError("equity باید بزرگ‌تر از صفر باشد.")
        else:
            snapshot = app.platform.accounts.latest_any()
            if snapshot is not None:
                equity = snapshot.equity
                equity_source = "account_snapshot"
            else:
                equity = Decimal("100")
                equity_source = "fallback"
        policy = app.platform.settings.risk
        recommendation = recommend_trading_settings(
            equity, policy, app.platform.instruments.list(),
        )
        return {
            "automated_limited": app.platform.phase_settings.to_dict()["automated_limited"],
            "equity": str(equity),
            "equity_source": equity_source,
            "policy": {
                "risk_per_trade": str(policy.risk_per_trade),
                "hard_cap_risk_per_trade": str(policy.hard_cap_risk_per_trade),
                "daily_loss_limit": str(policy.daily_loss_limit),
                "drawdown_warn": str(policy.drawdown_warn),
                "drawdown_stop": str(policy.drawdown_stop),
                "max_drawdown_hard_cap": str(policy.max_drawdown_hard_cap),
                "max_open_positions": policy.max_open_positions,
                "max_positions_per_symbol": policy.max_positions_per_symbol,
                "max_daily_trades": policy.max_daily_trades,
                "max_spread_pips": str(policy.max_spread_pips),
                "min_stop_pips": str(policy.min_stop_pips),
                "max_stop_pips": str(policy.max_stop_pips),
            },
            "recommendation": recommendation,
        }

    def _trading_settings_get(request, params, user):
        return app._json(200, _trading_settings_payload(request.one("equity")))

    def _trading_settings_update(request, params, user):
        body = request.json()
        confirm = bool(body.get("confirm_warnings"))
        values = body.get("automated_limited")
        if values is None:
            values = {key: value for key, value in body.items() if key != "confirm_warnings"}
        if not isinstance(values, dict):
            raise ValidationError("بدنه باید شیء تنظیمات باشد.")
        try:
            outcome = app.platform.apply_trading_settings(
                values, actor=user.username, confirm_warnings=confirm,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        if outcome.get("requires_confirmation"):
            return app._json(200, {
                **outcome,
                "note": "این مقادیر از سقف پیشنهادی بیرون‌اند؛ تا تأیید شما ذخیره نشد.",
            })
        app.settings = app.platform.settings
        app.platform.audit.append(
            "TRADING_SETTINGS_CHANGED", "automated_limited", "phase", actor=user.username,
            payload={
                "changed": sorted(values),
                "runtime_phase": outcome["runtime_phase"],
                "warnings": outcome.get("warnings", []),
            },
        )
        return app._json(200, {
            **outcome,
            "note": "تنظیمات معاملات ذخیره و در همین اجرا اعمال شد.",
        })

    # ===================================================================
    # ثبت مسیرها
    # ===================================================================
    app.routes.extend([
        # --- Trading ---
        ("GET",  re.compile(r"^/api/v1/trading/settings$"), _trading_settings_get, Permission.DATA_READ, False),
        ("POST", re.compile(r"^/api/v1/trading/settings$"), _trading_settings_update, Permission.SETTINGS_WRITE, False),
        ("GET",  re.compile(r"^/api/v1/trading/status$"), _broker_status, Permission.SCENARIO_READ, False),
        ("GET",  re.compile(r"^/api/v1/orders$"), _orders_list, Permission.SCENARIO_READ, False),
        ("GET",  re.compile(r"^/api/v1/orders/(?P<intent_id>[A-Za-z0-9_\-]+)/approval$"), _order_approval_get, Permission.SCENARIO_READ, False),
        ("POST", re.compile(r"^/api/v1/orders/(?P<intent_id>[A-Za-z0-9_\-]+)/approve$"), _order_approve, Permission.EXECUTION_APPROVE, False),
        ("POST", re.compile(r"^/api/v1/orders/(?P<intent_id>[A-Za-z0-9_\-]+)/reject$"), _order_reject, Permission.EXECUTION_APPROVE, False),
        ("POST", re.compile(r"^/api/v1/orders/(?P<intent_id>[A-Za-z0-9_\-]+)/submit$"), _order_submit_approved, Permission.EXECUTION_ORDER, False),
        ("GET",  re.compile(r"^/api/v1/orders/(?P<intent_id>[A-Za-z0-9_\-]+)$"), _orders_get, Permission.SCENARIO_READ, False),
        ("POST", re.compile(r"^/api/v1/orders$"), _orders_submit, Permission.EXECUTION_ORDER, False),
        ("POST", re.compile(r"^/api/v1/trading/reconcile$"), _reconcile, Permission.EXECUTION_ORDER, False),
        ("POST", re.compile(r"^/api/v1/trading/reconcile-closes$"), _reconcile_closes, Permission.EXECUTION_ORDER, False),
        ("GET",  re.compile(r"^/api/v1/trading/closed-trades$"), _closed_trades, Permission.REPORT_READ, False),
        ("GET",  re.compile(r"^/api/v1/trading/attribution$"), _attribution, Permission.REPORT_READ, False),
        ("POST", re.compile(r"^/api/v1/trading/forward-test$"), _forward_test, Permission.ANALYSIS_RUN, False),
        ("GET",  re.compile(r"^/api/v1/trading/positions$"), _positions_list, Permission.SCENARIO_READ, False),
        ("POST", re.compile(r"^/api/v1/trading/positions/(?P<ticket>\d+)/close$"), _close_position, Permission.EXECUTION_ORDER, False),
        ("POST", re.compile(r"^/api/v1/trading/broker-orders/(?P<broker_order_id>\d+)/cancel$"), _cancel_broker_order, Permission.EXECUTION_ORDER, False),

        # --- History ---
        ("POST", re.compile(r"^/api/v1/history/download$"), _history_download, Permission.DATA_INGEST, False),
        ("POST", re.compile(r"^/api/v1/history/ingest$"), _history_ingest, Permission.DATA_INGEST, False),
        ("GET",  re.compile(r"^/api/v1/history/files$"), _history_files, Permission.DATA_READ, False),

        # --- Strategy ---
        ("POST", re.compile(r"^/api/v1/strategy/analyze$"), _analyze_strategies, Permission.ANALYSIS_RUN, False),
        ("POST", re.compile(r"^/api/v1/strategy/trade$"), _trade_with_strategy, Permission.EXECUTION_ORDER, False),
        ("POST", re.compile(r"^/api/v1/strategy/trade_multi$"), _trade_multi_with_strategy, Permission.EXECUTION_ORDER, False),
        ("POST", re.compile(r"^/api/v1/trading/auto_trade$"), _set_auto_trade, Permission.SETTINGS_WRITE, False),
        ("GET",  re.compile(r"^/api/v1/trading/auto_trade$"), _get_auto_trade, Permission.SCENARIO_READ, False),
    ])
# FIX-31-AUTO-TRADE
# FIX-32-AUTO-LOG

# FIX-DUAL: TRADING-LOCKED
