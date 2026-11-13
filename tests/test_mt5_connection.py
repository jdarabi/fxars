"""اتصال مشترک MT5 و کش منفی نمادها."""

from __future__ import annotations

import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from fxars.live import mt5_connection
from fxars.live.mt5_feed import MT5Feed, MT5UnavailableError


class FakeMT5:
    def __init__(self) -> None:
        self.initialize_calls = 0
        self.shutdown_calls = 0
        self.symbol_scans = 0

    def initialize(self):
        self.initialize_calls += 1
        return True

    def shutdown(self):
        self.shutdown_calls += 1

    def last_error(self):
        return (0, "ok")

    def account_info(self):
        return SimpleNamespace(
            login=53255182, server="Alpari-MT5-Demo", currency="USD",
            balance=10000.0, equity=10000.0, margin_free=10000.0, leverage=100,
        )

    def copy_rates_from_pos(self, *args, **kwargs):
        return []

    def symbol_info(self, symbol):
        return None

    def symbol_select(self, symbol, enable):
        return False

    def symbols_get(self):
        self.symbol_scans += 1
        return []


class SharedConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        mt5_connection.reset_for_tests()

    def tearDown(self) -> None:
        mt5_connection.reset_for_tests()

    def test_release_only_shuts_down_last_reference(self) -> None:
        fake = FakeMT5()
        with mock.patch.dict(sys.modules, {"MetaTrader5": fake}):
            mt5_connection.acquire()
            mt5_connection.acquire()
            self.assertEqual(fake.initialize_calls, 1)
            mt5_connection.release()
            self.assertEqual(fake.shutdown_calls, 0)
            mt5_connection.release()
            self.assertEqual(fake.shutdown_calls, 1)

    def test_two_feeds_do_not_tear_down_each_other(self) -> None:
        fake = FakeMT5()
        with mock.patch.dict(sys.modules, {"MetaTrader5": fake}):
            first = MT5Feed(source_id="test")
            second = MT5Feed(source_id="test")
            first.shutdown()
            self.assertEqual(fake.shutdown_calls, 0)
            second.shutdown()
            self.assertEqual(fake.shutdown_calls, 1)


class NegativeSymbolCacheTests(unittest.TestCase):
    def _feed(self, fake: FakeMT5) -> MT5Feed:
        feed = MT5Feed.__new__(MT5Feed)
        feed._mt5 = fake
        feed._symbol_cache = {}
        feed._symbol_misses = {}
        feed.source_id = "test"
        return feed

    def test_missing_symbol_is_not_rescanned_immediately(self) -> None:
        fake = FakeMT5()
        feed = self._feed(fake)
        with self.assertRaises(MT5UnavailableError):
            feed._resolve_symbol("NOSUCH")
        with self.assertRaises(MT5UnavailableError):
            feed._resolve_symbol("NOSUCH")
        self.assertEqual(fake.symbol_scans, 1)

    def test_expired_miss_is_rescanned(self) -> None:
        fake = FakeMT5()
        feed = self._feed(fake)
        feed._symbol_misses["NOSUCH"] = (time.monotonic() - 1, "cached miss")
        with self.assertRaises(MT5UnavailableError):
            feed._resolve_symbol("NOSUCH")
        self.assertEqual(fake.symbol_scans, 1)


if __name__ == "__main__":
    unittest.main()
