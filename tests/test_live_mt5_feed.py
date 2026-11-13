"""FIX-LIVE-01: MT5 feed tests (skip if MT5 unavailable)."""
from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path as _P
from types import SimpleNamespace

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import MetaTrader5 as _mt5
    HAS_MT5 = True
except ImportError:
    HAS_MT5 = False


def _mt5_connected() -> bool:
    if not HAS_MT5:
        return False
    try:
        return bool(_mt5.initialize())
    except Exception:
        return False


@unittest.skipUnless(HAS_MT5 and _mt5_connected(), 'MT5 not installed or not logged in')
class MT5FeedLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fxars.live.mt5_feed import MT5Feed
        try:
            cls.feed = MT5Feed(source_id='mt5_test')
        except Exception as exc:
            raise unittest.SkipTest(f'MT5 unavailable: {exc}')

    @classmethod
    def tearDownClass(cls):
        cls.feed.shutdown()

    def test_account_info(self):
        info = self.feed.account_info()
        self.assertIn('login', info)
        self.assertGreater(info['balance'], 0)

    def test_symbol_info_eurusd(self):
        si = self.feed.symbol_info('EURUSD')
        self.assertIsNotNone(si)
        self.assertEqual(si['symbol'], 'EURUSD')
        self.assertIn(si['digits'], (3, 4, 5))

    def test_fetch_recent(self):
        candles = self.feed.fetch_recent('EURUSD', 'H1', count=10)
        self.assertGreater(len(candles), 0)
        for c in candles:
            self.assertEqual(c.instrument_id, 'EURUSD')
            self.assertEqual(c.timeframe, 'H1')
            self.assertTrue(c.is_closed)

    def test_fetch_new(self):
        candles = self.feed.fetch_recent('EURUSD', 'H1', count=20)
        if len(candles) < 5:
            self.skipTest('not enough candles')
        candles[-1]
        older = candles[-5]
        new = self.feed.fetch_new('EURUSD', 'H1', since=older.open_time, count=20)
        for c in new:
            self.assertGreater(c.open_time, older.open_time)


class _FakeRow(dict):
    def __init__(self, values, names):
        super().__init__(values)
        self.dtype = SimpleNamespace(names=names)


class _FakeRates(list):
    def __init__(self, rows, names):
        super().__init__(_FakeRow(row, names) for row in rows)


class _FakeMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_H1 = 2

    def __init__(self, h1_wall: datetime | None = None) -> None:
        self._now = datetime.now(tz=UTC)
        self._h1_wall = h1_wall or datetime(2026, 11, 6, 21, tzinfo=UTC)

    def copy_rates_from_pos(self, symbol, timeframe, pos, count):
        if timeframe == self.TIMEFRAME_M1:
            server_now = self._now + timedelta(hours=2)
            return _FakeRates([{"time": int(server_now.timestamp())}], ("time",))
        return _FakeRates(
            [{
                "time": int(self._h1_wall.timestamp()),
                "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15,
                "tick_volume": 100, "spread": 10,
            }],
            ("time", "open", "high", "low", "close", "tick_volume", "spread"),
        )

    def symbol_info(self, symbol):
        return SimpleNamespace(point=0.00001)


class HistoryOffsetTests(unittest.TestCase):
    """CSV تاریخچه نیز باید مثل فید زنده اختلاف زمان سرور را حذف کند."""

    def test_download_applies_broker_offset(self) -> None:
        from fxars.live.history import download_from_mt5

        candles = download_from_mt5(symbol="EURUSD", timeframe="H1", bars=1, mt5=_FakeMT5())

        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].open_time, datetime(2026, 11, 6, 19, tzinfo=UTC))
        self.assertEqual(candles[0].available_at, datetime(2026, 11, 6, 20, tzinfo=UTC))

    def test_download_applies_summer_dst_offset(self) -> None:
        from fxars.live.history import download_from_mt5

        # زمان دیواری سرور در ژوئیه (UTC+3) باید ۳ ساعت به عقب برود، نه ۲ ساعت.
        fake = _FakeMT5(h1_wall=datetime(2026, 7, 8, 12, tzinfo=UTC))
        candles = download_from_mt5(symbol="EURUSD", timeframe="H1", bars=1, mt5=fake)

        self.assertEqual(candles[0].open_time, datetime(2026, 7, 8, 9, tzinfo=UTC))


if __name__ == '__main__':
    unittest.main()
