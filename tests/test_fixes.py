"""تست‌های رگرسیون برای اصلاحات (Fixes 02-13)."""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from fxars.domain.enums import Direction, QualityStatus, ScenarioStatus
from fxars.domain.models import Candle, EconomicEvent, PriceZone, Scenario
from tests.helpers import ANALYST_PASSWORD, make_env


class Fix02VerdictSeverityTests(unittest.TestCase):
    def setUp(self) -> None:
        from fxars.config.settings import Settings
        from fxars.data.quality import DataQualityEngine
        from fxars.instruments.calendar import TradingCalendar, default_holidays
        self.env = make_env(bars=240)
        self.engine = DataQualityEngine(
            Settings.from_dict({"db_path": ":memory:"}).data_quality,
            TradingCalendar(default_holidays()),
        )

    def tearDown(self) -> None:
        self.env.close()

    def test_duplicate_yields_fail(self) -> None:
        candles = list(self.env.candles[:60])
        candles.append(candles[30])
        run = self.engine.evaluate(
            instrument=self.env.instrument, timeframe="H1", source_id="test",
            candles=candles, now=candles[-1].available_at,
        )
        self.assertEqual(run.verdict, "FAIL")


class Fix04FundamentalHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=300)

    def tearDown(self) -> None:
        self.env.close()

    def test_historical_evidence_produced(self) -> None:
        """FIX-04: Evidence بنیادی برای رویداد تاریخی (نه فقط ۲۴ ساعت آخر)."""
        # رویداد در میانه بازه
        event_time = self.env.candles[100].open_time
        event = EconomicEvent(
            event_id="evt_hist", indicator="CPI", currency="USD", country="US",
            event_time=event_time, published_at=event_time + timedelta(minutes=1),
            available_at=event_time + timedelta(minutes=2),
            importance="HIGH", actual="3.5", forecast="2.0", previous="1.8",
        )
        self.env.platform.events.save(event)

        # اجرای تحلیل
        result = self.env.analyze()

        # علاوه بر نتیجه ذخیره‌شده، Engine را مستقیم اجرا می‌کنیم تا ALL Evidenceها را ببینیم
        # (AnalysisService فقط Evidenceهای اخیر را ذخیره می‌کند)
        from fxars.data.snapshot import snapshot_id
        from datetime import timedelta as _td
        from fxars.domain.enums import QualityStatus as _QS

        candles = [
            c for c in self.env.platform.candles.range("EURUSD", "H1", source_id="demo_feed",
                                                      as_of=self.env.as_of, closed_only=True)
            if c.quality_status is not _QS.INVALID
        ]
        events = self.env.platform.events.between(
            candles[0].open_time - _td(hours=24), self.env.as_of, as_of=self.env.as_of,
        )
        self.assertGreater(len(events), 0, "رویداد تاریخی باید در between باشد")

        outcome = self.env.platform.analysis_engine.analyze(
            instrument=self.env.instrument, timeframe="H1",
            candles=candles, as_of=self.env.as_of, run_id="ar_hist_test",
            economic_events=events,
            config_hash="test",
        )
        fundamental = [ev for ev in outcome.evidences if ev.family.value == "FUNDAMENTAL"]
        self.assertGreater(len(fundamental), 0,
                           "Evidence بنیادی تاریخی باید در outcome.evidences باشد")


class Fix06RiskFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        from fxars.risk.account import parse_account_snapshot
        from fxars.risk.gate import RiskGate
        self.env = make_env(bars=240)
        self.gate = RiskGate(self.env.settings.risk, self.env.platform.killswitch, self.env.calendar)
        self.candle = Candle(
            instrument_id="EURUSD", source_id="test", timeframe="H1",
            open_time=self.env.as_of - timedelta(hours=1),
            open="1.0870", high="1.0890", low="1.0860", close="1.0880",
            spread=None, is_closed=True,
            ingested_at=self.env.as_of, available_at=self.env.as_of,
        )
        self.account = parse_account_snapshot({
            "equity": "10000", "balance": "10000", "free_margin": "10000",
            "taken_at": self.env.as_of.isoformat(), "currency": "USD", "leverage": "100",
            "open_positions": 0, "positions": [],
        })

    def tearDown(self) -> None:
        self.env.close()

    def _scenario(self) -> Scenario:
        return Scenario(
            scenario_id="sc_t", instrument_id="EURUSD", timeframe="H1", direction=Direction.LONG,
            status=ScenarioStatus.WATCH,
            entry_condition={"type": "price_cross_above", "level": "1.0900", "timeframe": "H1"},
            entry_zone=PriceZone("1.0898", "1.0902"),
            invalidation_condition={"type": "close_below", "level": "1.0850", "timeframe": "H1"},
            stop_logic={"type": "structure_low", "level": "1.0850"},
            target_logic=({"type": "rr_multiple", "value": 1.5, "price": "1.0975"},),
            expiry_at=self.env.as_of + timedelta(hours=8),
            evidence_ids=("ev",), analysis_run_id="ar", decision_explanation="test",
            created_at=self.env.as_of, updated_at=self.env.as_of,
            rules_version="v1", config_hash="h", strength=0.6,
        )

    def _evaluate(self, **overrides):
        from fxars.risk.gate import RiskContext
        values = dict(
            scenario=self._scenario(), account=self.account,
            instrument=self.env.instrument, candle=self.candle, events=(),
            instruments={"EURUSD": self.env.instrument},
            rates={"USD": Decimal("1")}, correlations={}, now=self.env.as_of,
        )
        values.update(overrides)
        return self.gate.evaluate(RiskContext(**values))

    def test_missing_spread_fails(self) -> None:
        decision = self._evaluate()
        self.assertIn("spread_within_limit", decision.checks_failed)

    def test_future_account_timestamp_fails(self) -> None:
        future = replace(self.account, taken_at=self.env.as_of + timedelta(hours=1))
        decision = self._evaluate(account=future, candle=replace(self.candle, spread=Decimal("0.0001")))
        self.assertIn("account_snapshot_fresh", decision.checks_failed)

    def test_entry_deviation_fails(self) -> None:
        far = replace(self.candle, close=Decimal("1.1500"), high=Decimal("1.1510"),
                      low=Decimal("1.1490"), spread=Decimal("0.0001"))
        decision = self._evaluate(candle=far)
        self.assertIn("entry_deviation_ok", decision.checks_failed)


class Fix07ApiValidationTests(unittest.TestCase):
    """FIX-07: ورودی نامعتبر ⇒ 400. این تست از توکن واقعی استفاده می‌کند."""

    def setUp(self) -> None:
        from fxars.api.server import ApiApp
        from fxars.domain.enums import Role
        self.env = make_env(bars=240, users=False)
        self.env.platform.identity.create_user("apitest", Role.ANALYST, "ApiTestPass123!")
        self.app = ApiApp(self.env.platform)
        self.token = self.env.platform.identity.login("apitest", "ApiTestPass123!").token

    def tearDown(self) -> None:
        self.env.close()

    def _post(self, path: str, body: dict, idem: str) -> int:
        import json
        from fxars.api.server import ApiRequest
        request = ApiRequest(
            method="POST", path=path, query={},
            headers={"authorization": f"Bearer {self.token}", "idempotency-key": idem,
                     "content-type": "application/json"},
            body=json.dumps(body).encode(), ip="127.0.0.1",
        )
        return self.app.handle(request).status

    def test_invalid_timeframe_returns_400(self) -> None:
        status = self._post("/api/v1/analysis-runs",
                            {"instrument_id": "EURUSD", "timeframe": "XYZ"}, "k_tf")
        self.assertEqual(status, 400)

    def test_invalid_as_of_returns_400(self) -> None:
        status = self._post("/api/v1/analysis-runs",
                            {"instrument_id": "EURUSD", "timeframe": "H1",
                             "as_of": "not-a-date"}, "k_as_of")
        self.assertEqual(status, 400)


class Fix12CandlesPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        from fxars.api.server import ApiApp
        from fxars.domain.enums import Role
        self.env = make_env(bars=240, users=False)
        self.env.platform.identity.create_user("candtest", Role.ANALYST, "CandTestPass123!")
        self.app = ApiApp(self.env.platform)
        self.token = self.env.platform.identity.login("candtest", "CandTestPass123!").token

    def tearDown(self) -> None:
        self.env.close()

    def _get(self, path: str) -> dict:
        import json
        from urllib.parse import parse_qs, urlparse
        from fxars.api.server import ApiRequest
        parsed = urlparse(path)
        request = ApiRequest(
            method="GET", path=parsed.path, query=parse_qs(parsed.query),
            headers={"authorization": f"Bearer {self.token}"},
            body=b"", ip="127.0.0.1",
        )
        response = self.app.handle(request)
        self.assertEqual(response.status, 200, response.body.decode()[:200])
        return json.loads(response.body.decode())

    def test_source_id_reported(self) -> None:
        payload = self._get("/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=1")
        self.assertEqual(payload.get("source_id"), "demo_feed")

    def test_offset(self) -> None:
        page1 = self._get("/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=5")
        page2 = self._get("/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=5&offset=5")
        self.assertGreater(len(page1["items"]), 0)
        self.assertGreater(len(page2["items"]), 0)
        self.assertNotEqual(page1["items"][-1]["bar_open_time_utc"],
                           page2["items"][-1]["bar_open_time_utc"])


class Fix13ResultHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(bars=500)

    def tearDown(self) -> None:
        self.env.close()

    def test_result_hash_deterministic(self) -> None:
        first = self.env.analyze()
        second = self.env.analyze()
        self.assertEqual(first.run.result_hash, second.run.result_hash)


if __name__ == "__main__":
    unittest.main()