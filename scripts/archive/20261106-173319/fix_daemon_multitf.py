# C:\FX\fix_daemon_multitf.py
"""Force-rewrite daemon.py with multi-timeframe + schedule support."""
from pathlib import Path
import shutil
import datetime

ROOT = Path(r'C:\FX')
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
BACKUP = ROOT / '.fix-backups' / f'daemon-multitf-{stamp}'
BACKUP.mkdir(parents=True, exist_ok=True)

path = ROOT / 'fxars/live/daemon.py'
shutil.copy2(path, BACKUP / 'daemon.py')
print(f'Backup: {BACKUP / "daemon.py"}')

content = '''"""FIX-LIVE-03-MTF: Live daemon with multi-timeframe + schedule."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fxars.core.timeutil import format_ts
from fxars.live.config import ScheduleConfig

logger = logging.getLogger("fxars.live.daemon")


@dataclass
class LiveDaemonConfig:
    instrument_id: str = "EURUSD"
    timeframe: str = "H1"
    timeframes: list[str] = field(default_factory=list)
    interval_seconds: int = 60
    history_bars: int = 500
    source_id: str = "mt5"
    log_path: str = "data/live/daemon.jsonl"
    min_score_threshold: float = 0.10
    send_no_trade: bool = False
    max_signals_per_hour: int = 3
    schedule: ScheduleConfig | None = None

    @classmethod
    def from_live_config(cls, live, *, log_path="data/live/daemon.jsonl"):
        return cls(
            instrument_id=live.instrument,
            timeframe=live.primary_timeframe,
            timeframes=list(live.timeframes) or [live.primary_timeframe],
            interval_seconds=live.interval_seconds,
            history_bars=live.history_bars,
            source_id=live.source_id,
            log_path=log_path,
            send_no_trade=live.send_no_trade,
            max_signals_per_hour=live.max_signals_per_hour,
            schedule=live.schedule,
        )


@dataclass
class LiveDaemonStats:
    cycles: int = 0
    candles_ingested: int = 0
    signals_sent: int = 0
    errors: int = 0
    skipped_by_schedule: int = 0
    last_run_id: str = ""
    last_decision: str = ""
    last_candle_time: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_dict(self) -> dict:
        return {
            "cycles": self.cycles,
            "candles_ingested": self.candles_ingested,
            "signals_sent": self.signals_sent,
            "errors": self.errors,
            "skipped_by_schedule": self.skipped_by_schedule,
            "last_run_id": self.last_run_id,
            "last_decision": self.last_decision,
            "last_candle_time": self.last_candle_time,
            "started_at": format_ts(self.started_at),
            "uptime_seconds": int((datetime.now(tz=timezone.utc) - self.started_at).total_seconds()),
        }


class LiveDaemon:
    def __init__(
        self,
        *,
        config: LiveDaemonConfig,
        platform: Any,
        feed: Any,
        notifier: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.platform = platform
        self.feed = feed
        self.notifier = notifier
        self._sleep = sleep_fn
        self._now = now_fn or (lambda: datetime.now(tz=timezone.utc))
        self._stop = False
        self.stats = LiveDaemonStats()
        self._last_candle_times: dict[str, datetime] = {}
        self._signal_times: list[datetime] = []
        self._last_signal_by_tf: dict[str, str] = {}
        self._log_path = Path(config.log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def stop(self) -> None:
        self._stop = True
        logger.info("daemon stop requested")

    def _log_event(self, event: dict[str, Any]) -> None:
        event.setdefault("ts", format_ts(self._now()))
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\\n")
        except Exception as exc:
            logger.warning("log write failed: %s", exc)

    def _schedule_allows(self) -> bool:
        if self.config.schedule is None:
            return True
        return self.config.schedule.should_run(self._now())

    def _can_send_signal(self) -> bool:
        import datetime as _dt
        cutoff = self._now() - _dt.timedelta(hours=1)
        self._signal_times = [t for t in self._signal_times if t > cutoff]
        return len(self._signal_times) < self.config.max_signals_per_hour

    def _ingest_new(self, tf: str) -> int:
        since = self._last_candle_times.get(tf)
        if since is None:
            candles = self.feed.fetch_recent(
                self.config.instrument_id, tf, count=self.config.history_bars,
            )
        else:
            candles = self.feed.fetch_new(
                self.config.instrument_id, tf, since=since, count=100,
            )
        if not candles:
            return 0
        result = self.platform.ingestion.ingest(
            candles,
            instrument_id=self.config.instrument_id,
            source_id=self.config.source_id,
            now=self._now(),
        )
        self._last_candle_times[tf] = candles[-1].open_time
        self._log_event({
            "event": "ingest",
            "timeframe": tf,
            "accepted": result.accepted,
            "quarantined": result.quarantined,
            "latest_candle": format_ts(candles[-1].open_time),
        })
        return result.accepted

    def _analyze(self, tf: str) -> Any:
        return self.platform.run_analysis(
            self.config.instrument_id, tf, actor="live-daemon",
        )

    def _maybe_notify(self, result: Any, tf: str) -> None:
        decision = result.decision
        action = decision.action.value
        if action == "NO_TRADE":
            if self.config.send_no_trade and self.notifier is not None:
                self.notifier.send_no_trade(result.run.run_id, decision.no_trade_reason or "")
            return
        if not self._can_send_signal():
            logger.info("rate limit: too many signals in last hour")
            return
        if self._last_signal_by_tf.get(tf) == action:
            logger.info("duplicate signal for %s, skipped: %s", tf, action)
            return
        if self.notifier is None:
            logger.warning("no notifier configured")
            return
        try:
            ok = self.notifier.send_signal(decision, result.scenario)
        except Exception as exc:
            logger.exception("notify failed: %s", exc)
            self.stats.errors += 1
            return
        if ok:
            self.stats.signals_sent += 1
            self._signal_times.append(self._now())
            self._last_signal_by_tf[tf] = action
            self._log_event({
                "event": "signal",
                "timeframe": tf,
                "action": action,
                "score": float(decision.score),
                "scenario_id": result.scenario.scenario_id if result.scenario else None,
            })

    def run_once(self) -> bool:
        self.stats.cycles += 1
        if not self._schedule_allows():
            self.stats.skipped_by_schedule += 1
            if self.stats.cycles % 30 == 0:
                logger.info("cycle %s: skipped by schedule", self.stats.cycles)
            return False

        sent_signal = False
        timeframes = self.config.timeframes or [self.config.timeframe]
        for tf in timeframes:
            try:
                n = self._ingest_new(tf)
                self.stats.candles_ingested += n
                result = self._analyze(tf)
                self.stats.last_run_id = result.run.run_id
                self.stats.last_decision = result.decision.action.value
                logger.info(
                    "cycle %s/%s: candles=%s decision=%s score=%+.3f",
                    self.stats.cycles, tf, n,
                    result.decision.action.value, result.decision.score,
                )
                self._maybe_notify(result, tf)
                if result.decision.action.value != "NO_TRADE":
                    sent_signal = True
            except Exception as exc:
                logger.exception("cycle %s/%s failed: %s", self.stats.cycles, tf, exc)
                self.stats.errors += 1
                self._log_event({
                    "event": "error",
                    "timeframe": tf,
                    "error": type(exc).__name__,
                    "message": str(exc),
                })
        return sent_signal

    def run(self, *, max_cycles: int | None = None) -> None:
        tfs = self.config.timeframes or [self.config.timeframe]
        logger.info(
            "daemon starting: %s/%s every %ss",
            self.config.instrument_id, tfs,
            self.config.interval_seconds,
        )
        self._log_event({
            "event": "start",
            "instrument": self.config.instrument_id,
            "timeframes": tfs,
            "interval_seconds": self.config.interval_seconds,
            "schedule": self.config.schedule.mode if self.config.schedule else "always",
        })
        try:
            while not self._stop:
                self.run_once()
                if max_cycles is not None and self.stats.cycles >= max_cycles:
                    logger.info("max_cycles=%s reached", max_cycles)
                    break
                for _ in range(self.config.interval_seconds):
                    if self._stop:
                        break
                    self._sleep(1)
        except KeyboardInterrupt:
            logger.info("interrupted")
        finally:
            self._log_event({"event": "stop", "stats": self.stats.to_dict()})
            logger.info("daemon stopped: %s", self.stats.to_dict())
'''

path.write_text(content, encoding='utf-8')
print(f'OK: {path} rewritten ({len(content)} bytes)')

import py_compile
try:
    py_compile.compile(str(path), doraise=True)
    print('syntax OK')
except py_compile.PyCompileError as exc:
    print('SYNTAX ERROR:', exc)
    raise SystemExit(1)