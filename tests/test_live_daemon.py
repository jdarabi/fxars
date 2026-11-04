"""FIX-LIVE-03: LiveDaemon tests (mock feed/notifier)."""
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
