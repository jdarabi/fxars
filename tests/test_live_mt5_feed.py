"""FIX-LIVE-01: MT5 feed tests (skip if MT5 unavailable)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path as _P

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
        last = candles[-1]
        older = candles[-5]
        new = self.feed.fetch_new('EURUSD', 'H1', since=older.open_time, count=20)
        for c in new:
            self.assertGreater(c.open_time, older.open_time)


if __name__ == '__main__':
    unittest.main()
