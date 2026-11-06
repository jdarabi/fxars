# C:\FX\install_live_phase3.py
"""Phase 3: live daemon."""
import datetime
import shutil
from pathlib import Path

ROOT = Path(r'C:\FX')
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
BACKUP = ROOT / '.fix-backups' / f'live-phase3-{stamp}'
BACKUP.mkdir(parents=True, exist_ok=True)


def backup(rel):
    src = ROOT / rel
    if not src.exists():
        return
    dst = BACKUP / rel.replace('\\', '__').replace('/', '__')
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def write_file(rel, content, marker=''):
    full = ROOT / rel
    if full.exists() and marker and marker in full.read_text(encoding='utf-8'):
        print(f'  [skip] {rel}')
        return
    if full.exists():
        backup(rel)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding='utf-8')
    print(f'  [wrote] {rel} ({len(content)} bytes)')


print('=== Phase 3: live daemon ===')
print(f'Backup: {BACKUP}')

# ============================================================
# fxars/live/daemon.py
# ============================================================
write_file('fxars/live/daemon.py', '''"""FIX-LIVE-03: Live daemon — loop تحلیل خودکار + هشدار.

هر interval ثانیه:
  1. کندل جدید از MT5
  2. ingest در DB
  3. تحلیل
  4. اگر سیگنال جدید بود → Telegram
  5. لاگ همه چیز

استفاده:
    from fxars.live.daemon import LiveDaemon, LiveDaemonConfig
    daemon = LiveDaemon(config)
    daemon.run()   # تا Ctrl+C
"""
from __future__ import annotations

import json
import logging
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fxars.core.timeutil import format_ts, timeframe_delta
from fxars.core.ids import stable_id

logger = logging.getLogger('fxars.live.daemon')


@dataclass
class LiveDaemonConfig:
    instrument_id: str = 'EURUSD'
    timeframe: str = 'H1'
    interval_seconds: int = 60
    history_bars: int = 500
    source_id: str = 'mt5'
    log_path: str = 'data/live/daemon.jsonl'
    min_score_threshold: float = 0.10
    send_no_trade: bool = False
    max_signals_per_hour: int = 3


@dataclass
class LiveDaemonStats:
    cycles: int = 0
    candles_ingested: int = 0
    signals_sent: int = 0
    errors: int = 0
    last_run_id: str = ''
    last_decision: str = ''
    last_candle_time: str = ''
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_dict(self) -> dict:
        return {
            'cycles': self.cycles,
            'candles_ingested': self.candles_ingested,
            'signals_sent': self.signals_sent,
            'errors': self.errors,
            'last_run_id': self.last_run_id,
            'last_decision': self.last_decision,
            'last_candle_time': self.last_candle_time,
            'started_at': format_ts(self.started_at),
            'uptime_seconds': int((datetime.now(tz=timezone.utc) - self.started_at).total_seconds()),
        }


class LiveDaemon:
    """حلقهٔ تحلیل خودکار."""

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
        self._last_candle_time: datetime | None = None
        self._signal_times: list[datetime] = []
        self._last_signal_direction: str = ''
        self._log_path = Path(config.log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def stop(self) -> None:
        self._stop = True
        logger.info('daemon stop requested')

    def _log_event(self, event: dict[str, Any]) -> None:
        event.setdefault('ts', format_ts(self._now()))
        try:
            with open(self._log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + '\\n')
        except Exception as exc:
            logger.warning('log write failed: %s', exc)

    def _can_send_signal(self) -> bool:
        cutoff = self._now() - __import__('datetime').timedelta(hours=1)
        self._signal_times = [t for t in self._signal_times if t > cutoff]
        return len(self._signal_times) < self.config.max_signals_per_hour

    def _ingest_new(self) -> int:
        """کندل‌های جدید را از MT5 بگیر و به DB بریز."""
        since = self._last_candle_time
        if since is None:
            # اولین اجرا — history کامل
            candles = self.feed.fetch_recent(
                self.config.instrument_id, self.config.timeframe,
                count=self.config.history_bars,
            )
        else:
            candles = self.feed.fetch_new(
                self.config.instrument_id, self.config.timeframe,
                since=since, count=100,
            )
        if not candles:
            return 0
        result = self.platform.ingestion.ingest(
            candles,
            instrument_id=self.config.instrument_id,
            source_id=self.config.source_id,
            now=self._now(),
        )
        self._last_candle_time = candles[-1].open_time
        self.stats.last_candle_time = format_ts(candles[-1].open_time)
        self._log_event({
            'event': 'ingest',
            'accepted': result.accepted,
            'quarantined': result.quarantined,
            'latest_candle': format_ts(candles[-1].open_time),
        })
        return result.accepted

    def _analyze(self) -> Any:
        return self.platform.run_analysis(
            self.config.instrument_id, self.config.timeframe,
            actor='live-daemon',
        )

    def _maybe_notify(self, result: Any) -> None:
        decision = result.decision
        action = decision.action.value
        if action == 'NO_TRADE':
            if self.config.send_no_trade and self.notifier is not None:
                self.notifier.send_no_trade(result.run.run_id, decision.no_trade_reason or '')
            return
        if not self._can_send_signal():
            logger.info('rate limit: too many signals in last hour')
            return
        # فقط سیگنال جهت‌دار جدید یا تغییر جهت
        if action == self._last_signal_direction:
            # همان جهت — دوباره هشدار نده
            logger.info('duplicate signal direction, skipped: %s', action)
            return
        if self.notifier is None:
            logger.warning('no notifier configured')
            return
        try:
            ok = self.notifier.send_signal(decision, result.scenario)
        except Exception as exc:
            logger.exception('notify failed: %s', exc)
            self.stats.errors += 1
            return
        if ok:
            self.stats.signals_sent += 1
            self._signal_times.append(self._now())
            self._last_signal_direction = action
            self._log_event({
                'event': 'signal',
                'action': action,
                'score': float(decision.score),
                'scenario_id': result.scenario.scenario_id if result.scenario else None,
            })

    def run_once(self) -> bool:
        """یک چرخهٔ کامل. True اگر سیگنال ارسال شد."""
        self.stats.cycles += 1
        try:
            n = self._ingest_new()
            self.stats.candles_ingested += n
            result = self._analyze()
            self.stats.last_run_id = result.run.run_id
            self.stats.last_decision = result.decision.action.value
            logger.info(
                'cycle %s: candles=%s decision=%s score=%+.3f',
                self.stats.cycles, n,
                result.decision.action.value, result.decision.score,
            )
            self._maybe_notify(result)
            return result.decision.action.value != 'NO_TRADE'
        except Exception as exc:
            logger.exception('cycle failed: %s', exc)
            self.stats.errors += 1
            self._log_event({'event': 'error', 'error': type(exc).__name__, 'message': str(exc)})
            return False

    def run(self, *, max_cycles: int | None = None) -> None:
        """حلقهٔ اصلی تا Ctrl+C یا max_cycles."""
        logger.info(
            'daemon starting: %s/%s every %ss',
            self.config.instrument_id, self.config.timeframe,
            self.config.interval_seconds,
        )
        self._log_event({
            'event': 'start',
            'instrument': self.config.instrument_id,
            'timeframe': self.config.timeframe,
            'interval_seconds': self.config.interval_seconds,
        })
        try:
            while not self._stop:
                self.run_once()
                if max_cycles is not None and self.stats.cycles >= max_cycles:
                    logger.info('max_cycles=%s reached', max_cycles)
                    break
                for _ in range(self.config.interval_seconds):
                    if self._stop:
                        break
                    self._sleep(1)
        except KeyboardInterrupt:
            logger.info('interrupted')
        finally:
            self._log_event({'event': 'stop', 'stats': self.stats.to_dict()})
            logger.info('daemon stopped: %s', self.stats.to_dict())
''', marker='FIX-LIVE-03')

# ============================================================
# tests/test_live_daemon.py
# ============================================================
write_file('tests/test_live_daemon.py', '''"""FIX-LIVE-03: LiveDaemon tests (mock feed/notifier)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path as _P
from unittest.mock import MagicMock

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.domain.enums import DecisionAction, Direction
from fxars.live.daemon import LiveDaemon, LiveDaemonConfig


@dataclass
class _FakeDecision:
    action: DecisionAction
    direction: Direction
    score: float
    coverage: float
    stability: float
    family_scores: dict
    no_trade_reason: str | None


@dataclass
class _FakeRun:
    run_id: str


@dataclass
class _FakeResult:
    run: _FakeRun
    decision: _FakeDecision
    scenario: object | None = None


class _FakeFeed:
    def __init__(self, candles_per_call: list[list]):
        self._candles_per_call = candles_per_call
        self._call = 0

    def fetch_recent(self, instrument_id, timeframe, count=500):
        if self._call < len(self._candles_per_call):
            result = self._candles_per_call[self._call]
            self._call += 1
            return result
        return []

    def fetch_new(self, instrument_id, timeframe, since, count=100):
        return self.fetch_recent(instrument_id, timeframe, count)


class _FakeNotifier:
    def __init__(self):
        self.sent = []
        self.no_trade = []

    def send_signal(self, decision, scenario=None):
        self.sent.append((decision.action, scenario))
        return True

    def send_no_trade(self, run_id, reason):
        self.no_trade.append((run_id, reason))
        return True


def _make_candle(dt):
    from fxars.domain.models import Candle
    return Candle(
        instrument_id='EURUSD', source_id='mt5_test', timeframe='H1',
        open_time=dt, open=Decimal('1.08'), high=Decimal('1.09'),
        low=Decimal('1.07'), close=Decimal('1.085'),
        ingested_at=dt, available_at=dt,
        spread=Decimal('0.0001'), is_closed=True,
    )


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_path = _P(self.tmp.name) / 'daemon.jsonl'

    def tearDown(self):
        self.tmp.cleanup()

    def _make_daemon(self, feed, notifier=None, decision=None, config=None):
        from tests.helpers import make_env
        env = make_env(bars=200)
        self.addCleanup(env.close)
        if decision is None:
            decision = _FakeDecision(
                action=DecisionAction.LONG, direction=Direction.LONG,
                score=0.42, coverage=0.43, stability=1.0,
                family_scores={'STRUCTURE': 0.12},
                no_trade_reason=None,
            )
        if config is None:
            config = LiveDaemonConfig(
                instrument_id='EURUSD', timeframe='H1',
                interval_seconds=1, log_path=str(self.log_path),
            )
        # Patch platform.run_analysis
        env.platform.run_analysis = MagicMock(return_value=_FakeResult(
            run=_FakeRun(run_id='ar_test'),
            decision=decision,
            scenario=None,
        ))
        daemon = LiveDaemon(
            config=config, platform=env.platform, feed=feed, notifier=notifier,
            sleep_fn=lambda s: None,
        )
        return daemon

    def test_run_once_with_signal(self):
        from datetime import timedelta
        now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
        feed = _FakeFeed([[_make_candle(now)]])
        notifier = _FakeNotifier()
        daemon = self._make_daemon(feed, notifier)
        result = daemon.run_once()
        self.assertTrue(result)
        self.assertEqual(len(notifier.sent), 1)
        self.assertEqual(notifier.sent[0][0], DecisionAction.LONG)

    def test_no_trade_does_not_notify(self):
        from datetime import timedelta
        now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
        feed = _FakeFeed([[_make_candle(now)]])
        notifier = _FakeNotifier()
        decision = _FakeDecision(
            action=DecisionAction.NO_TRADE, direction=Direction.NEUTRAL,
            score=0.05, coverage=0.1, stability=0.5,
            family_scores={}, no_trade_reason='INSUFFICIENT_EVIDENCE',
        )
        daemon = self._make_daemon(feed, notifier, decision=decision)
        daemon.run_once()
        self.assertEqual(len(notifier.sent), 0)

    def test_duplicate_direction_not_resent(self):
        from datetime import timedelta
        now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
        feed = _FakeFeed([
            [_make_candle(now)],
            [_make_candle(now + timedelta(hours=1))],
        ])
        notifier = _FakeNotifier()
        daemon = self._make_daemon(feed, notifier)
        daemon.run_once()
        daemon.run_once()
        self.assertEqual(len(notifier.sent), 1)

    def test_error_handling(self):
        feed = MagicMock()
        feed.fetch_recent.side_effect = RuntimeError('MT5 down')
        notifier = _FakeNotifier()
        daemon = self._make_daemon(feed, notifier)
        result = daemon.run_once()
        self.assertFalse(result)
        self.assertEqual(daemon.stats.errors, 1)
        self.assertEqual(len(notifier.sent), 0)

    def test_max_cycles(self):
        now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
        feed = _FakeFeed([[_make_candle(now)]])
        daemon = self._make_daemon(feed)
        daemon.run(max_cycles=2)
        self.assertEqual(daemon.stats.cycles, 2)


if __name__ == '__main__':
    unittest.main()
''', marker='FIX-LIVE-03')

print()
print('=== Phase 3 done ===')
print()
print('Test:')
print('  python -m unittest tests.test_live_daemon -v')
