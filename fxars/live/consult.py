"""Consultant: live advisor with optional AutoTrade (MT5 demo)."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fxars.live.advisor import Advice, AdviceAction, generate_advice
from fxars.live.config import LiveConfig
from fxars.live.desktop_notifier import DesktopConfig, DesktopNotifier
from fxars.live.mt5_feed import MT5Feed, MT5UnavailableError
from fxars.live.notifier import TelegramConfig, TelegramNotifier

logger = logging.getLogger("fxars.live.consult")


def _format_advice_telegram(advice: Advice) -> str:
    from fxars.live.notifier import _escape

    emoji = {
        AdviceAction.BUY: "🟢", AdviceAction.SELL: "🔴",
        AdviceAction.HOLD: "🟡", AdviceAction.EXIT: "🟠",
        AdviceAction.STAY_OUT: "⚪", AdviceAction.WAIT: "🔵",
    }.get(advice.action, "⚪")

    parts = [
        "<b>" + emoji + " " + _escape(advice.symbol) + " / " + _escape(advice.timeframe) + "</b>",
        "<b>پیشنهاد: " + _escape(advice.action.value) + "</b>",
        "اعتماد: " + format(advice.confidence, ".0%"),
        "",
        _escape(advice.reason),
    ]
    if advice.entry is not None:
        parts.append("")
        parts.append("ورود: <code>" + _escape(str(advice.entry)) + "</code>")
        if advice.stop is not None:
            parts.append("حد ضرر: <code>" + _escape(str(advice.stop)) + "</code>")
        for i, t in enumerate(advice.targets[:2], 1):
            parts.append("هدف " + str(i) + ": <code>" + _escape(str(t)) + "</code>")
    if advice.suggestions:
        parts.append("")
        parts.append("<b>پیشنهادها:</b>")
        for s in advice.suggestions[:4]:
            parts.append("• " + _escape(s))
    return "\n".join(parts)



def _apply_trailing_sl(trailing_pips: int = 20) -> int:
    """Apply trailing stop loss to all open positions.
    
    Returns number of positions updated.
    """
    try:
        import MetaTrader5 as mt5
        positions = mt5.positions_get()
        if not positions:
            return 0
        
        updated = 0
        for p in positions:
            si = mt5.symbol_info(p.symbol)
            if si is None:
                continue
            
            current = p.price_current
            entry = p.price_open
            
            if si.digits == 3:  # JPY
                buffer_points = trailing_pips
            elif si.digits == 2:  # XAU
                buffer_points = trailing_pips * 10
            else:  # 5-digit
                buffer_points = trailing_pips * 10
            
            if p.type == 1:  # SELL
                new_sl = current + si.point * buffer_points
                if p.sl > 0 and new_sl >= p.sl:
                    continue  # not better
                if new_sl > entry:
                    new_sl = entry  # at worst breakeven
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": p.ticket,
                    "symbol": p.symbol,
                    "sl": float(new_sl),
                    "tp": float(p.tp),
                }
            else:  # BUY
                new_sl = current - si.point * buffer_points
                if p.sl > 0 and new_sl <= p.sl:
                    continue
                if new_sl < entry:
                    new_sl = entry
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": p.ticket,
                    "symbol": p.symbol,
                    "sl": float(new_sl),
                    "tp": float(p.tp),
                }
            
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                updated += 1
        
        return updated
    except Exception:
        return 0


def _apply_trailing_sl(trailing_pips: int = 20) -> int:
    """Apply trailing stop to all open positions. Returns count updated."""
    try:
        import MetaTrader5 as mt5
        positions = mt5.positions_get()
        if not positions:
            return 0

        updated = 0
        for p in positions:
            si = mt5.symbol_info(p.symbol)
            if si is None:
                continue

            current = p.price_current
            entry = p.price_open

            if si.digits == 3:  # JPY
                buffer_points = trailing_pips
            elif si.digits == 2:  # XAU
                buffer_points = trailing_pips * 10
            else:  # 5-digit forex
                buffer_points = trailing_pips * 10

            if p.type == 1:  # SELL
                new_sl = current + si.point * buffer_points
                if p.sl > 0 and new_sl >= p.sl:
                    continue
                if new_sl > entry:
                    new_sl = entry
            else:  # BUY
                new_sl = current - si.point * buffer_points
                if p.sl > 0 and new_sl <= p.sl:
                    continue
                if new_sl < entry:
                    new_sl = entry

            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": p.ticket,
                "symbol": p.symbol,
                "sl": float(new_sl),
                "tp": float(p.tp),
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                updated += 1
                print(f"           trailing {p.symbol}: SL -> {new_sl}", file=sys.stderr)

        return updated
    except Exception as exc:
        print(f"           trailing error: {exc}", file=sys.stderr)
        return 0


class Consultant:
    def __init__(
        self,
        *,
        platform: Any,
        feed: Any,
        config: LiveConfig,
        telegram: TelegramNotifier | None = None,
        desktop: DesktopNotifier | None = None,
        auto_trade: bool = False,
    ) -> None:
        self.platform = platform
        self.feed = feed
        self.config = config
        self.telegram = telegram
        self.desktop = desktop
        self.auto_trade = auto_trade
        self._last_signals: dict[tuple[str, str], str] = {}
        self._signal_times: list[datetime] = []

    def _rate_ok(self) -> bool:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        self._signal_times = [t for t in self._signal_times if t > cutoff]
        return len(self._signal_times) < self.config.max_signals_per_hour

    def _open_positions_count(self) -> int:
        """Count open MT5 positions without re-initializing (uses existing MT5Feed connection)."""
        try:
            import MetaTrader5 as mt5
            positions = mt5.positions_get()
            return len(positions) if positions else 0
        except Exception:
            return 0

    def run_once(self) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        instruments = self.config.instruments or [self.config.instrument]
        timeframes = self.config.timeframes or [self.config.primary_timeframe]

        for symbol in instruments:
            for tf in timeframes:
                try:
                    if not self.platform.instruments.find(symbol):
                        continue

                    candles = self.feed.fetch_recent(symbol, tf, count=self.config.history_bars)
                    if not candles:
                        continue

                    self.platform.ingestion.ingest(
                        candles, instrument_id=symbol,
                        source_id=self.config.source_id,
                        now=datetime.now(tz=timezone.utc),
                    )

                    result = self.platform.run_analysis(symbol, tf, actor="consultant")
                    d = result.decision
                    sc = result.scenario

                    instrument = self.platform.instruments.find(symbol)
                    advice = generate_advice(
                        decision=d, scenario=sc, symbol=symbol, timeframe=tf,
                        risk_decision=None, instrument_spec=instrument,
                    )

                    info = {
                        "symbol": symbol, "timeframe": tf,
                        "action": advice.action.value,
                        "confidence": advice.confidence,
                        "score": float(d.score),
                        "scenario_id": sc.scenario_id if sc else None,
                    }
                    signals.append(info)
                    self._print_signal(info, advice)

                    # AutoTrade or notify
                    actionable = advice.action.value in ("BUY", "SELL")
                    if actionable:
                        if self.auto_trade:
                            self._try_auto_trade(symbol, tf, sc, advice, info)
                        else:
                            self._notify(symbol, tf, advice)

                except MT5UnavailableError as exc:
                    print(f"[{symbol:8s}/{tf:3s}] MT5 error: {exc}", file=sys.stderr)
                except Exception as exc:
                    print(f"[{symbol:8s}/{tf:3s}] {type(exc).__name__}: {exc}", file=sys.stderr)

        # Apply trailing SL to all positions
        n_updated = _apply_trailing_sl(40)
        if n_updated > 0:
            print(f'           -> trailing SL updated on {n_updated} position(s)', file=sys.stderr)

        # Apply trailing SL
        n_updated = _apply_trailing_sl(40)
        if n_updated > 0:
            print(f'           -> trailing updated on {n_updated} position(s)', file=sys.stderr)

        return signals

    def _try_auto_trade(self, symbol: str, tf: str, sc: Any, advice: Advice, info: dict[str, Any]) -> None:
        """Attempt to send an order via ExecutionService."""
        open_count = self._open_positions_count()
        max_pos = self.platform.settings.risk.max_open_positions
        if open_count >= max_pos:
            print(f"           -> AutoTrade skipped (already {open_count} open positions)", file=sys.stderr)
            return

        try:
            import MetaTrader5 as mt5
            existing = mt5.positions_get(symbol=symbol)
            if existing:
                print(f"           -> AutoTrade skipped ({symbol} already has position)", file=sys.stderr)
                return
        except Exception:
            pass

        if not self._rate_ok():
            print(f"           -> AutoTrade skipped (rate limit)", file=sys.stderr)
            return

        if sc is None:
            print(f"           -> AutoTrade skipped (no scenario)", file=sys.stderr)
            return

        # FIX-SCENARIO: if DRAFT, try evaluate; if still DRAFT, find existing WATCH/ARMED
        if sc is not None and sc.status.value == 'DRAFT':
            try:
                eval_result = self.platform.evaluate_scenario(sc.scenario_id)
                sc = eval_result.scenario
                print(f'           -> evaluated: {sc.status.value}', file=sys.stderr)
            except Exception as exc:
                print(f'           -> eval failed: {exc}', file=sys.stderr)

        # If still DRAFT, look for existing WATCH/ARMED scenario for this symbol
        if sc is not None and sc.status.value == 'DRAFT':
            try:
                live = self.platform.scenarios.list(instrument_id=symbol, limit=20)
                for s in live:
                    if s.status.value in ('WATCH', 'ARMED', 'TRIGGERED') and s.timeframe == tf:
                        sc = s
                        print(f'           -> using existing {s.status.value} scenario', file=sys.stderr)
                        break
            except Exception:
                pass

        if sc is None or sc.status.value not in ('WATCH', 'ARMED', 'TRIGGERED'):
            print(f'           -> AutoTrade skipped (no valid scenario)', file=sys.stderr)
            return


        key = (symbol, tf)
        if self._last_signals.get(key) == advice.action.value:
            print(f"           -> AutoTrade skipped (duplicate {advice.action.value})", file=sys.stderr)
            return

        try:
            from fxars.risk.account import demo_account
            from decimal import Decimal
            import MetaTrader5 as mt5

            si = mt5.symbol_info(symbol)
            if si is None:
                print(f"           -> AutoTrade skipped ({symbol} not in MT5)", file=sys.stderr)
                return
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                print(f"           -> AutoTrade skipped (no tick)", file=sys.stderr)
                return

            # Determine pip_size and rate
            if si.digits == 3:  # JPY pairs
                pip_size = Decimal("0.01")
                quote_to_usd = Decimal("1") / Decimal(str(tick.bid))
            elif si.digits == 2:  # XAUUSD
                pip_size = Decimal("0.1")
                quote_to_usd = Decimal("1")
            else:  # 5-digit forex
                pip_size = Decimal("0.0001")
                quote_to_usd = Decimal("1")

            print(f"           pip_size={pip_size} quote_to_usd={quote_to_usd}", file=sys.stderr)

            # Build rates dict
            rates = {"USD": "1"}
            if si.currency_profit.upper() != "USD":
                rates[si.currency_profit.upper()] = str(quote_to_usd)

            account = demo_account("100000")
            risk = self.platform.evaluate_risk(sc.scenario_id, account, rates=rates)
            if not risk.approved:
                print(f"           -> AutoTrade rejected by RiskGate ({risk.reason_code.value})", file=sys.stderr)
                return

            intent = self.platform.execution.create_intent(sc.scenario_id, actor="consultant")
            price = Decimal(str(tick.ask if intent.side.value == "BUY" else tick.bid))
            result = self.platform.execution.submit(
                intent.intent_id, price=price, pip_size=pip_size, actor="consultant",
            )

            if result.status.value == "FILLED":
                print(f"           -> AutoTrade FILLED: {intent.instrument_id} {intent.side.value} {intent.volume} lot", file=sys.stderr)
                self._last_signals[key] = advice.action.value
                self._signal_times.append(datetime.now(tz=timezone.utc))
                if self.desktop:
                    try: self.desktop.send_advice(advice)
                    except Exception: pass
                if self.telegram:
                    try: self.telegram.send_message(_format_advice_telegram(advice))
                    except Exception: pass
            else:
                print(f"           -> AutoTrade {result.status.value}", file=sys.stderr)
        except Exception as exc:
            print(f"           -> AutoTrade error: {exc}", file=sys.stderr)

    def _notify(self, symbol: str, tf: str, advice: Advice) -> None:
        key = (symbol, tf)
        if not self._rate_ok():
            return
        if self._last_signals.get(key) == advice.action.value:
            return

        if self.desktop:
            try:
                ok = self.desktop.send_advice(advice)
                print(f"           -> Desktop {'OK' if ok else 'FAIL'}", file=sys.stderr)
            except Exception as exc:
                print(f"           -> Desktop error: {exc}", file=sys.stderr)
        if self.telegram:
            try:
                ok = self.telegram.send_message(_format_advice_telegram(advice))
                print(f"           -> Telegram {'OK' if ok else 'FAIL'}", file=sys.stderr)
            except Exception as exc:
                print(f"           -> Telegram error: {exc}", file=sys.stderr)
        self._last_signals[key] = advice.action.value
        self._signal_times.append(datetime.now(tz=timezone.utc))

    def _print_signal(self, info: dict[str, Any], advice: Advice) -> None:
        symbol = info["symbol"]
        tf = info["timeframe"]
        action = info["action"]
        conf = info["confidence"]
        score = info["score"]
        color = {
            "BUY": "\033[92m", "SELL": "\033[91m",
            "HOLD": "\033[93m", "EXIT": "\033[33m",
            "WAIT": "\033[94m", "STAY_OUT": "\033[90m",
        }.get(action, "\033[90m")
        reset = "\033[0m"
        print(f"{color}[{symbol:8s}/{tf:3s}] {action:8s} conf={conf:.0%} score={score:+.3f}{reset}")
        for s in advice.suggestions[:2]:
            print(f"           • {s}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fxars consult")
    parser.add_argument("--live-config", default="config/live.json")
    parser.add_argument("--instruments", nargs="+", default=None)
    parser.add_argument("--timeframes", nargs="+", default=None)
    parser.add_argument("--interval", type=int, default=0)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--no-desktop", action="store_true")
    parser.add_argument("--auto-trade", action="store_true",
                        help="Automatically send orders to MT5 demo (DANGEROUS)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    config = LiveConfig.load(args.live_config)
    if args.instruments:
        config.instruments = list(args.instruments)
        config.instrument = args.instruments[0]
    if args.timeframes:
        config.timeframes = list(args.timeframes)
    if args.interval:
        config.interval_seconds = args.interval

    from fxars.platform import Platform
    from fxars.config.settings import Settings
    platform = Platform(Settings.load())

    if args.auto_trade and not platform.settings.execution_enabled:
        print("ERROR: --auto-trade requires phase DEMO/PAPER/AUTOMATED_LIMITED", file=sys.stderr)
        return 2

    try:
        feed = MT5Feed(source_id=config.source_id)
        print("MT5 connected", file=sys.stderr)
    except MT5UnavailableError as exc:
        print(f"MT5 unavailable: {exc}", file=sys.stderr)
        return 2

    telegram = None
    if not args.no_telegram:
        tg = TelegramConfig.from_env()
        if tg is not None:
            try:
                telegram = TelegramNotifier(tg)
                print(f"Telegram enabled (chat_id={tg.chat_id})", file=sys.stderr)
            except Exception as exc:
                print(f"Telegram disabled: {exc}", file=sys.stderr)

    desktop = None
    if not args.no_desktop:
        try:
            desktop = DesktopNotifier(DesktopConfig())
            print(f"Desktop enabled (method={desktop._method})", file=sys.stderr)
        except Exception as exc:
            print(f"Desktop disabled: {exc}", file=sys.stderr)

    mode = "AUTO-TRADE" if args.auto_trade else "ADVISOR"
    print(f"\n=== FX-ARS Consultant ({mode}) ===", file=sys.stderr)
    print(f"Instruments: {config.instruments}", file=sys.stderr)
    print(f"Timeframes:  {config.timeframes}", file=sys.stderr)
    print(f"Interval:    {config.interval_seconds}s ({config.interval_seconds//60}min)", file=sys.stderr)
    print(f"Max signals/hour: {config.max_signals_per_hour}", file=sys.stderr)
    if args.auto_trade:
        print(f"⚠️  AUTO-TRADE ENABLED: orders will be sent to MT5", file=sys.stderr)
    print(f"\nPress Ctrl+C to stop.\n", file=sys.stderr)

    consultant = Consultant(
        platform=platform, feed=feed, config=config,
        telegram=telegram, desktop=desktop,
        auto_trade=args.auto_trade,
    )

    cycles = 0
    try:
        while True:
            cycles += 1
            print(f"\n--- Cycle {cycles} @ {datetime.now().strftime('%H:%M:%S')} ---", file=sys.stderr)
            consultant.run_once()
            if args.max_cycles and cycles >= args.max_cycles:
                print(f"Reached max_cycles={args.max_cycles}", file=sys.stderr)
                break
            time.sleep(config.interval_seconds)
    except KeyboardInterrupt:
        print("\nStopped by user", file=sys.stderr)
    finally:
        try:
            feed.shutdown()
        except Exception:
            pass
        platform.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
