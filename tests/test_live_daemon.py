"""FIX-LIVE-03: LiveDaemon tests (mock feed/notifier)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path as _P
from types import SimpleNamespace
from unittest.mock import MagicMock

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.config.settings import AutomatedLimitedSettings
from fxars.domain.enums import DecisionAction, Direction, Phase, ScenarioStatus
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
        instrument_id='EURUSD', source_id='mt5', timeframe='H1',
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
        now = datetime(2026, 11, 4, 12, tzinfo=UTC)
        feed = _FakeFeed([[_make_candle(now)]])
        notifier = _FakeNotifier()
        daemon = self._make_daemon(feed, notifier)
        result = daemon.run_once()
        self.assertTrue(result)
        self.assertEqual(len(notifier.sent), 1)
        self.assertEqual(notifier.sent[0][0], DecisionAction.LONG)

    def test_no_trade_does_not_notify(self):
        now = datetime(2026, 11, 4, 12, tzinfo=UTC)
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
        now = datetime(2026, 11, 4, 12, tzinfo=UTC)
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
        now = datetime(2026, 11, 4, 12, tzinfo=UTC)
        feed = _FakeFeed([[_make_candle(now)]])
        daemon = self._make_daemon(feed)
        daemon.run(max_cycles=2)
        self.assertEqual(daemon.stats.cycles, 2)


class _SafetyFeed:
    def __init__(self, *, currency="USD", equity="11000", balance="10500", realized="-300"):
        self.currency = currency
        self.equity = Decimal(equity)
        self.balance = Decimal(balance)
        self.realized = Decimal(realized)

    def account_snapshot(self):
        return {
            "login": 123456,
            "server": "broker-demo",
            "currency": self.currency,
            "balance": self.balance,
            "equity": self.equity,
            "margin_free": Decimal("10000"),
            "margin_used": Decimal("500"),
            "leverage": Decimal("100"),
        }

    def open_positions(self):
        return []

    def realized_pnl_since(self, start):
        return self.realized

    def symbol_info(self, symbol):
        if symbol == "USDJPY":
            return {"currency_profit": "JPY", "currency_base": "USD", "point": 0.001, "digits": 3}
        if symbol == "EURUSD":
            return {"currency_profit": "USD", "currency_base": "EUR", "point": 0.0001, "digits": 5}
        return None

    def tick(self, symbol):
        if symbol == "USDJPY":
            return {"bid": Decimal("149.9"), "ask": Decimal("150.1")}
        if symbol == "EURUSD":
            return {"bid": Decimal("1.0850"), "ask": Decimal("1.0852")}
        return None


class DaemonSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = datetime(2026, 11, 10, 12, tzinfo=UTC)
        self.previous = SimpleNamespace(
            peak_equity=Decimal("12000"), equity=Decimal("11500"),
        )
        self.automated = AutomatedLimitedSettings(
            enabled=True, max_volume_per_order=Decimal("0.01"),
            max_open_positions=1, max_daily_trades=3,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _platform(self, *, broker_name="mt5", trades_today=0):
        return SimpleNamespace(
            settings=SimpleNamespace(
                phase=Phase.AUTOMATED_LIMITED,
                execution_enabled=True,
                risk=SimpleNamespace(max_spread_pips=Decimal("3.0")),
            ),
            phase_settings=SimpleNamespace(automated_limited=self.automated),
            clock=lambda: self.now,
            accounts=SimpleNamespace(latest=lambda account_id: self.previous),
            orders=SimpleNamespace(count_intents_since=lambda day_start: trades_today),
            killswitch=SimpleNamespace(is_active=lambda: False),
            execution=SimpleNamespace(broker=SimpleNamespace(name=broker_name)),
        )

    def _daemon(self, feed=None, *, broker_name="mt5", trades_today=0):
        config = LiveDaemonConfig(
            instrument_id="EURUSD", timeframe="H1", interval_seconds=1,
            log_path=str(_P(self.tmp.name) / "daemon.jsonl"),
            execute_orders=True,
        )
        return LiveDaemon(
            config=config, platform=self._platform(broker_name=broker_name, trades_today=trades_today),
            feed=feed or _SafetyFeed(), sleep_fn=lambda s: None,
            now_fn=lambda: self.now,
        )

    def test_account_snapshot_uses_history_peak_and_daily_pnl(self):
        account = self._daemon()._build_account_from_mt5(self.automated)
        self.assertEqual(account.peak_equity, Decimal("12000"))
        # realized -300 + floating (11000-10500) = +200
        self.assertEqual(account.daily_pnl, Decimal("200"))

    def test_rates_fail_closed_when_pair_missing(self):
        daemon = self._daemon()
        rates, missing = daemon._compute_rates(["USDJPY", "GBPJPY"])
        self.assertAlmostEqual(float(rates["JPY"]), 1 / 150.0, places=6)
        self.assertIn("GBPJPY", missing)

    def test_volume_cap_blocks_order(self):
        daemon = self._daemon()
        reason = daemon._execution_block_reason(
            instrument="EURUSD", timeframe="H1",
            account=SimpleNamespace(open_positions=0),
            decision=SimpleNamespace(position_size=Decimal("0.02")),
            scenario=SimpleNamespace(status=ScenarioStatus.TRIGGERED),
            automated=self.automated,
            tick={"bid": Decimal("1.0850"), "ask": Decimal("1.0852")},
            symbol_info={"point": 0.0001, "digits": 5},
        )
        self.assertEqual(reason, "VOLUME_0.02>0.01")

    def test_paper_broker_is_rejected(self):
        daemon = self._daemon(broker_name="paper")
        reason = daemon._execution_block_reason(
            instrument="EURUSD", timeframe="H1",
            account=SimpleNamespace(open_positions=0),
            decision=SimpleNamespace(position_size=Decimal("0.01")),
            scenario=SimpleNamespace(status=ScenarioStatus.TRIGGERED),
            automated=self.automated,
            tick={"bid": Decimal("1.0850"), "ask": Decimal("1.0852")},
            symbol_info={"point": 0.0001, "digits": 5},
        )
        self.assertEqual(reason, "REAL_BROKER_UNAVAILABLE")

    def test_daily_trade_cap_blocks_order(self):
        daemon = self._daemon(trades_today=3)
        reason = daemon._execution_block_reason(
            instrument="EURUSD", timeframe="H1",
            account=SimpleNamespace(open_positions=0),
            decision=SimpleNamespace(position_size=Decimal("0.01")),
            scenario=SimpleNamespace(status=ScenarioStatus.TRIGGERED),
            automated=self.automated,
            tick={"bid": Decimal("1.0850"), "ask": Decimal("1.0852")},
            symbol_info={"point": 0.0001, "digits": 5},
        )
        self.assertEqual(reason, "MAX_DAILY_TRADES")


class PhaseReloadTests(unittest.TestCase):
    def setUp(self):
        from fxars.config.settings import PhaseSettings

        self.tmp = tempfile.TemporaryDirectory()
        self.phase_path = _P(self.tmp.name) / "phase.json"
        self.phase_path.write_text(
            __import__("json").dumps(PhaseSettings(mode="PAPER").to_dict()), encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _daemon(self, *, mode="READ_ONLY", apply_outcome=None):
        from fxars.config.settings import AutomatedLimitedSettings

        platform = SimpleNamespace(
            phase_path=self.phase_path,
            phase_settings=SimpleNamespace(
                mode=mode,
                automated_limited=AutomatedLimitedSettings(),
            ),
            apply_phase=MagicMock(return_value=apply_outcome or {
                "previous_phase": "READ_ONLY", "runtime_phase": "PAPER",
                "requested_mode": "PAPER", "execution_enabled": True, "broker": "paper",
            }),
        )
        config = LiveDaemonConfig(
            instrument_id="EURUSD", timeframe="H1", interval_seconds=1,
            log_path=str(_P(self.tmp.name) / "daemon.jsonl"), reload_phase=True,
        )
        return LiveDaemon(config=config, platform=platform, feed=MagicMock(), sleep_fn=lambda s: None)

    def test_changed_mode_is_applied_without_restart(self):
        daemon = self._daemon(mode="READ_ONLY")
        daemon._sync_runtime_phase()
        daemon.platform.apply_phase.assert_called_once_with(
            "PAPER", automated_enabled=False, persist=False,
        )

    def test_unchanged_mode_does_not_touch_platform(self):
        daemon = self._daemon(mode="PAPER")
        daemon._sync_runtime_phase()
        daemon.platform.apply_phase.assert_not_called()

    def test_changed_trading_settings_reload_without_mode_change(self):
        from fxars.config.settings import PhaseSettings

        data = PhaseSettings(mode="PAPER").to_dict()
        data["automated_limited"]["max_volume_per_order"] = "0.05"
        self.phase_path.write_text(__import__("json").dumps(data), encoding="utf-8")
        daemon = self._daemon(mode="PAPER")
        daemon._sync_runtime_phase()
        daemon.platform.apply_phase.assert_called_once_with(
            "PAPER", automated_enabled=False, persist=False,
        )

    def test_reload_disabled_by_default(self):
        from fxars.config.settings import AutomatedLimitedSettings

        platform = SimpleNamespace(
            phase_path=self.phase_path,
            phase_settings=SimpleNamespace(mode="READ_ONLY", automated_limited=AutomatedLimitedSettings()),
            apply_phase=MagicMock(),
        )
        config = LiveDaemonConfig(instrument_id="EURUSD", log_path=str(_P(self.tmp.name) / "d.jsonl"))
        daemon = LiveDaemon(config=config, platform=platform, feed=MagicMock(), sleep_fn=lambda s: None)
        daemon._sync_runtime_phase()
        platform.apply_phase.assert_not_called()


if __name__ == '__main__':
    unittest.main()
