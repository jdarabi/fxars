"""Consultant: live advisor with Desktop + Telegram notifications.

Reads candles from MT5, runs analysis, generates actionable advice
(BUY/SELL/HOLD/EXIT/WAIT), notifies via Desktop (Windows toast) + Telegram.
Does NOT send orders (READ_ONLY phase).
"""
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
    """HTML format for Telegram."""
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


class Consultant:
    """Advisor: analyze live candles, print signals, notify Desktop + Telegram."""

    def __init__(
        self,
        *,
        platform: Any,
        feed: Any,
        config: LiveConfig,
        telegram: TelegramNotifier | None = None,
        desktop: DesktopNotifier | None = None,
    ) -> None:
        self.platform = platform
        self.feed = feed
        self.config = config
        self.telegram = telegram
        self.desktop = desktop
        self._last_signals: dict[tuple[str, str], str] = {}
        self._signal_times: list[datetime] = []

    def _rate_ok(self) -> bool:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        self._signal_times = [t for t in self._signal_times if t > cutoff]
        return len(self._signal_times) < self.config.max_signals_per_hour

    def run_once(self) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        instruments = self.config.instruments or [self.config.instrument]
        timeframes = self.config.timeframes or [self.config.primary_timeframe]

        for symbol in instruments:
            for tf in timeframes:
                try:
                    if not self.platform.instruments.find(symbol):
                        print(f"[{symbol:8s}/{tf:3s}] instrument not registered, skipping", file=sys.stderr)
                        continue

                    candles = self.feed.fetch_recent(symbol, tf, count=self.config.history_bars)
                    if not candles:
                        print(f"[{symbol:8s}/{tf:3s}] no candles", file=sys.stderr)
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
                        "symbol": symbol,
                        "timeframe": tf,
                        "action": d.action.value,
                        "advice_action": advice.action.value,
                        "confidence": advice.confidence,
                        "score": float(d.score),
                        "scenario_id": sc.scenario_id if sc else None,
                    }
                    signals.append(info)
                    self._print_signal(info, advice)

                    # Desktop + Telegram for actionable advice
                    actionable = advice.action.value in ("BUY", "SELL", "EXIT")
                    if actionable and self._rate_ok():
                        key = (symbol, tf)
                        if self._last_signals.get(key) != advice.action.value:
                            # Desktop
                            if self.desktop is not None:
                                try:
                                    ok = self.desktop.send_advice(advice)
                                    print(f"           -> Desktop {'OK' if ok else 'FAIL'}", file=sys.stderr)
                                except Exception as exc:
                                    print(f"           -> Desktop error: {exc}", file=sys.stderr)

                            # Telegram
                            if self.telegram is not None:
                                try:
                                    msg = _format_advice_telegram(advice)
                                    ok = self.telegram.send_message(msg)
                                    print(f"           -> Telegram {'OK' if ok else 'FAIL'}", file=sys.stderr)
                                except Exception as exc:
                                    print(f"           -> Telegram error: {exc}", file=sys.stderr)

                            self._last_signals[key] = advice.action.value
                            self._signal_times.append(datetime.now(tz=timezone.utc))
                        else:
                            print(f"           -> skipped (duplicate {advice.action.value})", file=sys.stderr)
                    elif actionable:
                        print(f"           -> skipped (rate limit)", file=sys.stderr)

                except MT5UnavailableError as exc:
                    print(f"[{symbol:8s}/{tf:3s}] MT5 error: {exc}", file=sys.stderr)
                except Exception as exc:
                    print(f"[{symbol:8s}/{tf:3s}] {type(exc).__name__}: {exc}", file=sys.stderr)

        return signals

    def _print_signal(self, info: dict[str, Any], advice: Advice) -> None:
        symbol = info["symbol"]
        tf = info["timeframe"]
        action = info["advice_action"]
        conf = info["confidence"]
        score = info["score"]
        color = {
            "BUY": "\033[92m", "SELL": "\033[91m",
            "HOLD": "\033[93m", "EXIT": "\033[33m",
            "WAIT": "\033[94m", "STAY_OUT": "\033[90m",
        }.get(action, "\033[90m")
        reset = "\033[0m"
        print(f"{color}[{symbol:8s}/{tf:3s}] {action:8s} conf={conf:.0%} score={score:+.3f}{reset}")
        for s in advice.suggestions[:3]:
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
        else:
            print("Telegram disabled (env vars not set)", file=sys.stderr)

    desktop = None
    if not args.no_desktop:
        try:
            desktop = DesktopNotifier(DesktopConfig())
            print(f"Desktop enabled (method={desktop._method})", file=sys.stderr)
        except Exception as exc:
            print(f"Desktop disabled: {exc}", file=sys.stderr)

    consultant = Consultant(
        platform=platform, feed=feed, config=config,
        telegram=telegram, desktop=desktop,
    )

    print(f"\n=== FX-ARS Consultant ===", file=sys.stderr)
    print(f"Instruments: {config.instruments}", file=sys.stderr)
    print(f"Timeframes:  {config.timeframes}", file=sys.stderr)
    print(f"Interval:    {config.interval_seconds}s", file=sys.stderr)
    print(f"Max signals/hour: {config.max_signals_per_hour}", file=sys.stderr)
    print(f"\nPress Ctrl+C to stop.\n", file=sys.stderr)

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