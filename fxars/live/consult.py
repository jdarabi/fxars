"""Consultant: live advisor for selected instruments/timeframes.

Reads candles from MT5, runs analysis, prints/notifies signals.
Does NOT send orders (READ_ONLY phase).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fxars.live.config import LiveConfig
from fxars.live.mt5_feed import MT5Feed, MT5UnavailableError
from fxars.live.notifier import TelegramConfig, TelegramNotifier

logger = logging.getLogger("fxars.live.consult")


def _format_signal_with_context(decision, scenario, symbol, timeframe):
    """Format signal with explicit symbol + timeframe."""
    from fxars.live.notifier import _escape

    action = decision.action.value if hasattr(decision.action, "value") else str(decision.action)
    direction = decision.direction.value if hasattr(decision.direction, "value") else str(decision.direction)
    score = float(decision.score) if decision.score is not None else 0.0
    coverage = float(decision.coverage) if decision.coverage is not None else 0.0
    stability = float(decision.stability) if decision.stability is not None else 0.0
    family_scores = decision.family_scores or {}

    parts = [
        "<b>FX-ARS SIGNAL</b>",
        "<b>" + _escape(symbol) + "</b> / <b>" + _escape(timeframe) + "</b>",
        "Action: <b>" + _escape(action) + "</b> | Direction: <b>" + _escape(direction) + "</b>",
        "Score: " + format(score, "+.3f") + "  Coverage: " + format(coverage, ".0%") + "  Stability: " + format(stability, ".0%"),
    ]
    if family_scores:
        joined = ", ".join(k + "=" + format(v, "+.2f") for k, v in family_scores.items())
        parts.append("<i>Families</i>: " + _escape(joined))

    if scenario is not None:
        parts.append("")
        parts.append("<b>SCENARIO</b>")
        entry = scenario.entry_condition or {}
        stop_logic = scenario.stop_logic or {}
        targets = scenario.target_logic or ()
        parts.append(
            "Entry: <b>" + _escape(str(entry.get("type", "—"))) + "</b> "
            + "@ <code>" + _escape(str(entry.get("level", "—"))) + "</code>"
        )
        parts.append("Stop : <code>" + _escape(str(stop_logic.get("level", "—"))) + "</code>")
        for idx, t in enumerate(targets[:2], start=1):
            parts.append(
                "TP" + str(idx) + "  : <code>" + _escape(str(t.get("price", "—"))) + "</code> "
                + "(" + _escape(str(t.get("value", "—"))) + "R)"
            )
        exp = scenario.expiry_at
        if exp is not None:
            parts.append("Expiry: " + _escape(exp.isoformat()))

    parts.append("")
    parts.append("<i>— برای تأیید / رد، به داشبورد مراجعه کن —</i>")
    return "\n".join(parts)

class Consultant:
    """Advisor: analyze live candles, print signals, notify Telegram."""

    def __init__(
        self,
        *,
        platform: Any,
        feed: Any,
        config: LiveConfig,
        notifier: TelegramNotifier | None = None,
    ) -> None:
        self.platform = platform
        self.feed = feed
        self.config = config
        self.notifier = notifier
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
                    # Ensure instrument exists
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
                    action = d.action.value
                    score = float(d.score)

                    info = {
                        "symbol": symbol,
                        "timeframe": tf,
                        "action": action,
                        "score": score,
                        "no_trade_reason": d.no_trade_reason,
                        "scenario_id": result.scenario.scenario_id if result.scenario else None,
                        "entry": result.scenario.entry_condition.get("level") if result.scenario else None,
                        "stop": result.scenario.stop_logic.get("level") if result.scenario else None,
                        "targets": [t.get("price") for t in (result.scenario.target_logic or ())] if result.scenario else [],
                        "expiry": result.scenario.expiry_at.isoformat() if result.scenario else None,
                    }
                    signals.append(info)
                    self._print_signal(info)

                    if action in ("LONG", "SHORT") and self.notifier is not None:
                        key = (symbol, tf)
                        if self._last_signals.get(key) != action:
                            if self._rate_ok():
                                msg = _format_signal_with_context(d, result.scenario, symbol, tf)
                                self.notifier.send_message(msg)
                                self._last_signals[key] = action
                                self._signal_times.append(datetime.now(tz=timezone.utc))
                                print(f"           -> Telegram sent", file=sys.stderr)
                            else:
                                print(f"           -> Telegram skipped (rate limit)", file=sys.stderr)
                        else:
                            print(f"           -> Telegram skipped (duplicate {action})", file=sys.stderr)

                except MT5UnavailableError as exc:
                    print(f"[{symbol:8s}/{tf:3s}] MT5 error: {exc}", file=sys.stderr)
                except Exception as exc:
                    print(f"[{symbol:8s}/{tf:3s}] {type(exc).__name__}: {exc}", file=sys.stderr)

        return signals

    def _print_signal(self, info: dict[str, Any]) -> None:
        symbol = info["symbol"]
        tf = info["timeframe"]
        action = info["action"]
        score = info["score"]
        if action == "LONG":
            color = "\033[92m"
        elif action == "SHORT":
            color = "\033[91m"
        else:
            color = "\033[90m"
        reset = "\033[0m"
        print(f"{color}[{symbol:8s}/{tf:3s}] {action:8s} score={score:+.3f}{reset}")
        if info.get("scenario_id"):
            print(f"           Entry: {info['entry']}  Stop: {info['stop']}  Targets: {info['targets']}")
            print(f"           Expiry: {info['expiry']}")
        if info.get("no_trade_reason"):
            print(f"           Reason: {info['no_trade_reason']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fxars consult")
    parser.add_argument("--live-config", default="config/live.json")
    parser.add_argument("--instruments", nargs="+", default=None)
    parser.add_argument("--timeframes", nargs="+", default=None)
    parser.add_argument("--interval", type=int, default=0)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--no-telegram", action="store_true")
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

    notifier = None
    if not args.no_telegram:
        tg = TelegramConfig.from_env()
        if tg is not None:
            try:
                notifier = TelegramNotifier(tg)
                print(f"Telegram enabled (chat_id={tg.chat_id})", file=sys.stderr)
            except Exception as exc:
                print(f"Telegram disabled: {exc}", file=sys.stderr)
        else:
            print("Telegram disabled (env vars not set)", file=sys.stderr)

    consultant = Consultant(platform=platform, feed=feed, config=config, notifier=notifier)

    print(f"\n=== FX-ARS Consultant ===", file=sys.stderr)
    print(f"Instruments: {config.instruments}", file=sys.stderr)
    print(f"Timeframes:  {config.timeframes}", file=sys.stderr)
    print(f"Interval:    {config.interval_seconds}s", file=sys.stderr)
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
