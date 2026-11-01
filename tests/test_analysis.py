"""آزمون موتور تحلیل: اندیکاتورها، ساختار، شواهد و بازتولید."""

from __future__ import annotations

import unittest
from datetime import timedelta
from decimal import Decimal

from fxars.analysis import indicators as ind
from fxars.analysis.context import AnalysisContext, IndicatorSet
from fxars.analysis.engine import AnalysisEngine
from fxars.analysis.evidence import EvidenceFactory
from fxars.analysis.structure import StructureModule, detect_breaks, detect_fvgs, find_swings
from fxars.data.synthetic import generate_candles
from fxars.domain.enums import Direction, EvidenceFamily
from fxars.domain.models import Candle
from tests.helpers import make_env


class IndicatorTests(unittest.TestCase):
    def test_sma(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(ind.sma(values, 3), [None, None, 2.0, 3.0, 4.0])

    def test_ema_starts_after_period(self) -> None:
        series = ind.ema([1.0] * 10, 3)
        self.assertIsNone(series[1])
        self.assertAlmostEqual(series[2], 1.0)

    def test_rsi_bounds(self) -> None:
        values = [float(index) for index in range(40)]
        series = [value for value in ind.rsi(values, 14) if value is not None]
        self.assertTrue(series)
        self.assertTrue(all(0 <= value <= 100 for value in series))
        self.assertGreater(series[-1], 90)

    def test_atr_positive(self) -> None:
        highs = [2.0, 3.0, 4.0, 5.0, 6.0] * 5
        lows = [1.0, 2.0, 3.0, 4.0, 5.0] * 5
        closes = [1.5, 2.5, 3.5, 4.5, 5.5] * 5
        series = [value for value in ind.atr(highs, lows, closes, 5) if value is not None]
        self.assertTrue(series)
        self.assertGreater(series[-1], 0)


class StructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=260)

    def tearDown(self) -> None:
        self.env.close()

    def test_swings_confirmed_after_k_bars(self) -> None:
        swings = find_swings(self.env.candles, k=3)
        self.assertTrue(swings)
        for swing in swings:
            self.assertEqual(swing.confirmed_index, swing.index + 3)
            self.assertLess(swing.confirmed_index, len(self.env.candles))

    def test_breaks_have_direction(self) -> None:
        swings = find_swings(self.env.candles, 3)
        breaks = detect_breaks(self.env.candles, swings)
        self.assertTrue(breaks)
        for event in breaks:
            self.assertIn(event.direction_name, ("LONG", "SHORT"))
            self.assertIn(event.kind, ("BOS_UP", "BOS_DOWN", "CHOCH_UP", "CHOCH_DOWN"))

    def test_fvg_geometry(self) -> None:
        env = self.env
        fvgs = detect_fvgs(env.candles, IndicatorSet.build(env.candles, env.settings.analysis).atr,
                           Decimal("0.2"))
        for fvg in fvgs:
            self.assertLess(fvg.zone.low, fvg.zone.high)
            if fvg.direction is Direction.LONG:
                self.assertGreater(env.candles[fvg.index].low, env.candles[fvg.index - 2].high)
            else:
                self.assertLess(env.candles[fvg.index].high, env.candles[fvg.index - 2].low)

    def test_structure_evidence_no_lookahead(self) -> None:
        env = self.env
        indicators = IndicatorSet.build(env.candles, env.settings.analysis)
        context = AnalysisContext(
            instrument=env.instrument, timeframe="H1", candles=env.candles, as_of=env.as_of,
            settings=env.settings.analysis, indicators=indicators, calendar=env.calendar,
        )
        factory = EvidenceFactory(context, "ar_test")
        module = StructureModule()
        module.compute(context, factory)
        evidences = factory.created
        self.assertTrue(evidences)
        for evidence in evidences:
            self.assertLessEqual(evidence.available_at, env.as_of)
            self.assertGreaterEqual(evidence.available_at, evidence.observed_at)


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=600)

    def tearDown(self) -> None:
        self.env.close()

    def test_engine_produces_evidence(self) -> None:
        engine = AnalysisEngine(self.env.settings.analysis, self.env.calendar)
        outcome = engine.analyze(
            instrument=self.env.instrument, timeframe="H1", candles=self.env.candles,
            as_of=self.env.as_of, run_id="ar_test", config_hash="hash",
        )
        self.assertEqual(outcome.status, "COMPLETED")
        self.assertTrue(outcome.evidences)
        families = {evidence.family for evidence in outcome.evidences}
        self.assertIn(EvidenceFamily.STRUCTURE, families)
        self.assertIn(EvidenceFamily.TREND, families)
        self.assertIn("last_close", outcome.summary)
        self.assertEqual(outcome.summary["bars"], len(self.env.candles))

    def test_insufficient_data(self) -> None:
        engine = AnalysisEngine(self.env.settings.analysis, self.env.calendar)
        outcome = engine.analyze(
            instrument=self.env.instrument, timeframe="H1", candles=self.env.candles[:50],
            as_of=self.env.as_of, run_id="ar_test",
        )
        self.assertEqual(outcome.status, "INSUFFICIENT_DATA")
        self.assertEqual(outcome.evidences, [])

    def test_analysis_reproducible(self) -> None:
        first = self.env.analyze()
        second = self.env.analyze()
        self.assertEqual(first.run.run_id, second.run.run_id)
        self.assertEqual(first.run.result_hash, second.run.result_hash)
        self.assertEqual([item.evidence_id for item in first.evidences],
                         [item.evidence_id for item in second.evidences])

    def test_stale_data_returns_no_trade(self) -> None:
        later = self.env.candles[-1].available_at + timedelta(days=7)
        self.env.clock.set(later)
        result = self.env.platform.run_analysis("EURUSD", "H1", as_of=later)
        self.assertEqual(result.run.status.value, "STALE")
        self.assertEqual(result.decision.no_trade_reason, "DATA_STALE")
        self.assertEqual(result.scenario, None)


if __name__ == "__main__":
    unittest.main()
