"""Storage protocol parity tests (P4-1)."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.domain.models import Candle, Instrument
from fxars.storage.db import Database
from fxars.storage.protocol import DatabaseProtocol, InMemoryDatabase
from fxars.storage.repositories import CandleRepository, InstrumentRepository


def _make_candle(index: int, price: float = 1.08) -> Candle:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Candle(
        instrument_id="EURUSD", source_id="test", timeframe="H1",
        open_time=start.replace(hour=index),
        open=Decimal(str(price)), high=Decimal(str(price + 0.001)),
        low=Decimal(str(price - 0.001)), close=Decimal(str(price + 0.0005)),
        ingested_at=start.replace(hour=index, second=30),
        available_at=start.replace(hour=index, second=30),
        spread=Decimal("0.0001"), is_closed=True,
    )


class ProtocolTests(unittest.TestCase):
    def test_database_implements_protocol(self):
        db = Database(":memory:")
        try:
            self.assertIsInstance(db, DatabaseProtocol)
        finally:
            db.close()

    def test_inmemory_implements_protocol(self):
        db = InMemoryDatabase()
        try:
            self.assertIsInstance(db, DatabaseProtocol)
        finally:
            db.close()


class ParityTests(unittest.TestCase):
    def _run_parity(self, db):
        db.migrate()
        repo = CandleRepository(db)
        candles = [_make_candle(i) for i in range(3)]
        repo.bulk_upsert(candles)
        result = repo.range("EURUSD", "H1")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].open, Decimal("1.08"))
        return result

    def test_parity_sqlite(self):
        db = Database(":memory:")
        try:
            result = self._run_parity(db)
            self.assertEqual(len(result), 3)
        finally:
            db.close()

    def test_parity_inmemory(self):
        db = InMemoryDatabase()
        try:
            result = self._run_parity(db)
            self.assertEqual(len(result), 3)
        finally:
            db.close()

    def test_instrument_parity(self):
        for factory in (lambda: Database(":memory:"), InMemoryDatabase):
            db = factory()
            try:
                db.migrate()
                repo = InstrumentRepository(db)
                inst = Instrument(
                    instrument_id="TEST", symbol="TEST",
                    base_currency="USD", quote_currency="USD",
                    digits=5, point=Decimal("0.00001"), pip_size=Decimal("0.0001"),
                    contract_size=Decimal("100000"), min_lot=Decimal("0.01"),
                    lot_step=Decimal("0.01"), max_lot=Decimal("100"),
                    tick_size=Decimal("0.00001"), tick_value=Decimal("1"),
                    profit_currency="USD", margin_rate=Decimal("0.01"),
                    stop_level_points=0, freeze_level_points=0,
                    swap_long=Decimal("0"), swap_short=Decimal("0"),
                    commission_per_lot=Decimal("0"),
                )
                repo.save(inst)
                loaded = repo.get("TEST")
                self.assertEqual(loaded.instrument_id, "TEST")
                self.assertEqual(loaded.pip_size, Decimal("0.0001"))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()