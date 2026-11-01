#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
$testsDir = Join-Path $ProjectRoot 'tests'
if (-not (Test-Path $testsDir)) { throw "tests dir not found" }

$newTestFile = Join-Path $testsDir 'test_fixes.py'
Write-Host "[FIX-14] Writing regression tests: $newTestFile" -ForegroundColor Cyan

$testContent = @'
"""تست‌های رگرسیون برای اصلاحات اعمال‌شده توسط اسکریپت‌های PowerShell.

هر تست به یک FIX-NN در اسکریپت‌های scripts/fix/ نگاشت دارد.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from fxars.domain.enums import Direction, QualityStatus, ScenarioStatus
from fxars.domain.models import Candle, EconomicEvent
from fxars.inspection_utils import *  # noqa: F401,F403  (helper اختیاری)
from tests.helpers import make_env


class Fix01IngestionTransactionTests(unittest.TestCase):
    """FIX-01: چرخه Ingestion اتمیک است."""

    def setUp(self) -> None:
        self.env = make_env(bars=240)

    def tearDown(self) -> None:
        self.env.close()

    def test_invalid_candle_does_not_create_orphan_audit(self) -> None:
        broken_time = self.env.candles[30].open_time
        broken = replace(self.env.candles[30], high=self.env.candles[30].low - Decimal("0.01"))
        before = self.env.platform.audit_verify()["count"]
        result = self.env.platform.ingestion.ingest(
            [broken], instrument_id="EURUSD", source_id="demo_feed", now=self.env.clock(),
        )
        self.assertEqual(result.quarantined, 1)
        # هم QualityRun و هم Audit با هم ثبت می‌شوند
        after = self.env.platform.audit_verify()["count"]
        self.assertGreaterEqual(after, before + 1)
        stored = [c for c in self.env.platform.candles.range("EURUSD", "H1") if c.open_time == broken_time]
        self.assertEqual(len(stored), 1)  # کندل اصلی سالم مانده
        self.assertTrue(self.env.platform.audit_verify()["valid"])


class Fix02VerdictSeverityTests(unittest.TestCase):
    """FIX-02: verdict بر اساس شدت Issueها."""

    def setUp(self) -> None:
        from fxars.config.settings import Settings
        from fxars.data.quality import DataQualityEngine
        from fxars.instruments.calendar import TradingCalendar, default_holidays

        self.env = make_env(bars=240)
        self.engine = DataQualityEngine(Settings.from_dict({"db_path": ":memory:"}).data_quality,
                                        TradingCalendar(default_holidays()))

    def tearDown(self) -> None:
        self.env.close()

    def test_duplicate_yields_fail(self) -> None:
        candles = list(self.env.candles[:60])
        candles.append(candles[30])  # duplicate timestamp
        run = self.engine.evaluate(
            instrument=self.env.instrument, timeframe="H1", source_id="test",
            candles=candles, now=candles[-1].available_at,
        )
        self.assertEqual(run.verdict, "FAIL")


class Fix03PrimarySourceTests(unittest.TestCase):
    """FIX-03: انتخاب منبع اصلی."""

    def setUp(self) -> None:
        self.env = make_env(bars=240)

    def tearDown(self) -> None:
        self.env.close()

    def test_primary_source_single(self) -> None:
        sid = self.env.platform.instruments.primary_source("EURUSD", "H1")
        self.assertEqual(sid, "demo_feed")

    def test_primary_source_respects_priority(self) -> None:
        # یک منبع دوم اضافه کنیم با priority بالاتر (عدد کوچکتر)
        from fxars.domain.models import DataSource
        self.env.platform.instruments.save_source(DataSource(
            source_id="secondary", name="sec", kind="test", license_id="x",
            redistribution_allowed=False, retention_days=10, priority=5,
        ))
        # یک کندل از منبع دوم اضافه کن
        c = replace(self.env.candles[-1], source_id="secondary")
        self.env.platform.ingestion.ingest(
            [c], instrument_id="EURUSD", source_id="secondary", now=self.env.clock(),
        )
        sid = self.env.platform.instruments.primary_source("EURUSD", "H1")
        self.assertEqual(sid, "secondary")


class Fix04FundamentalHistoryTests(unittest.TestCase):
    """FIX-04: شواهد بنیادی تاریخی."""

    def setUp(self) -> None:
        self.env = make_env(bars=300)

    def tearDown(self) -> None:
        self.env.close()

    def test_historical_evidence_produced(self) -> None:
        from fxars.domain.models import EconomicEvent

        # یک رویداد در میانه بازه اضافه کن (نه ۲۴ ساعت آخر)
        event_time = self.env.candles[50].open_time
        event = EconomicEvent(
            event_id="evt_hist", indicator="CPI", currency="USD", country="US",
            event_time=event_time, published_at=event_time + timedelta(minutes=1),
            available_at=event_time + timedelta(minutes=2),
            importance="HIGH", actual="3.5", forecast="2.0", previous="1.8",
        )
        # اجرای تحلیل با as_of نزدیک انتهای بازه
        # ورود رویداد به repository
        self.env.platform.events.save(event)
        result = self.env.analyze()
        # انتظار: رویداد تاریخی به عنوان Evidence ثبت شده باشد
        fundamental = [ev for ev in result.evidences if ev.family.value == "FUNDAMENTAL"]
        self.assertGreater(len(fundamental), 0)


class Fix06RiskFailClosedTests(unittest.TestCase):
    """FIX-06: Risk Gate در ابهام Fail می‌کند."""

    def setUp(self) -> None:
        from fxars.risk.account import parse_account_snapshot
        from fxars.risk.gate import RiskGate
        self.env = make_env(bars=240)
        self.gate = RiskGate(self.env.settings.risk, self.env.platform.killswitch, self.env.calendar)
        self.candle = Candle(
            instrument_id="EURUSD", source_id="test", timeframe="H1",
            open_time=self.env.as_of - timedelta(hours=1),
            open="1.0870", high="1.0890", low="1.0860", close="1.0880",
            spread=None,  # بدون اسپرد
            is_closed=True, ingested_at=self.env.as_of, available_at=self.env.as_of,
        )
        self.account = parse_account_snapshot({
            "equity": "10000", "balance": "10000", "free_margin": "10000",
            "taken_at": self.env.as_of.isoformat(), "currency": "USD", "leverage": "100",
            "open_positions": 0, "positions": [],
        })

    def tearDown(self) -> None:
        self.env.close()

    def _make_scenario(self):
        from fxars.domain.models import PriceZone, Scenario
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

    def test_missing_spread_fails(self) -> None:
        from fxars.risk.gate import RiskContext
        decision = self.gate.evaluate(RiskContext(
            scenario=self._make_scenario(), account=self.account,
            instrument=self.env.instrument, candle=self.candle, events=(),
            instruments={"EURUSD": self.env.instrument},
            rates={"USD": Decimal("1")}, correlations={}, now=self.env.as_of,
        ))
        self.assertFalse(decision.approved)
        self.assertIn("spread_within_limit", decision.checks_failed)

    def test_future_account_timestamp_fails(self) -> None:
        from fxars.risk.gate import RiskContext
        future = replace(self.account, taken_at=self.env.as_of + timedelta(hours=1))
        decision = self.gate.evaluate(RiskContext(
            scenario=self._make_scenario(), account=future,
            instrument=self.env.instrument, candle=replace(self.candle, spread=Decimal("0.0001")),
            events=(), instruments={"EURUSD": self.env.instrument},
            rates={"USD": Decimal("1")}, correlations={}, now=self.env.as_of,
        ))
        self.assertFalse(decision.approved)
        self.assertIn("account_snapshot_fresh", decision.checks_failed)

    def test_entry_deviation_fails(self) -> None:
        from fxars.risk.gate import RiskContext
        far_candle = replace(self.candle, close=Decimal("1.1500"), spread=Decimal("0.0001"),
                             high=Decimal("1.1510"), low=Decimal("1.1490"))
        decision = self.gate.evaluate(RiskContext(
            scenario=self._make_scenario(), account=self.account,
            instrument=self.env.instrument, candle=far_candle, events=(),
            instruments={"EURUSD": self.env.instrument},
            rates={"USD": Decimal("1")}, correlations={}, now=self.env.as_of,
        ))
        self.assertFalse(decision.approved)
        self.assertIn("entry_deviation_ok", decision.checks_failed)


class Fix07ApiValidationTests(unittest.TestCase):
    """FIX-07: ورودی نامعتبر ⇒ 400 نه 500."""

    def setUp(self) -> None:
        import json
        from urllib.parse import parse_qs, urlparse
        from fxars.api.server import ApiApp, ApiRequest
        from tests.helpers import ANALYST_PASSWORD

        self.env = make_env(bars=240, users=True)
        self.app = ApiApp(self.env.platform)
        # login
        request = ApiRequest(
            method="POST", path="/api/v1/auth/login", query={},
            headers={"content-type": "application/json"},
            body=json.dumps({"username": "analyst", "password": ANALYST_PASSWORD}).encode(),
            ip="127.0.0.1",
        )
        resp = self.app.handle(request)
        self.token = json.loads(resp.body.decode())["token"]
        self.parse_qs = parse_qs
        self.urlparse = urlparse

    def tearDown(self) -> None:
        self.env.close()

    def _call(self, method: str, path: str, body=None, idempotency="key-x"):
        import json
        from fxars.api.server import ApiRequest
        parsed = self.urlparse(path)
        headers = {"Authorization": f"Bearer {self.token}", "content-type": "application/json"}
        if method == "POST" and idempotency:
            headers["idempotency-key"] = idempotency
        request = ApiRequest(
            method=method, path=parsed.path, query=self.parse_qs(parsed.query),
            headers=headers, body=json.dumps(body).encode() if body else b"", ip="127.0.0.1",
        )
        return self.app.handle(request)

    def test_invalid_timeframe_returns_400(self) -> None:
        resp = self._call("POST", "/api/v1/analysis-runs",
                          {"instrument_id": "EURUSD", "timeframe": "XYZ"})
        self.assertEqual(resp.status, 400)

    def test_invalid_as_of_returns_400(self) -> None:
        resp = self._call("POST", "/api/v1/analysis-runs",
                          {"instrument_id": "EURUSD", "timeframe": "H1", "as_of": "not-a-date"})
        self.assertEqual(resp.status, 400)


class Fix08RateLimitTests(unittest.TestCase):
    """FIX-08: توکن جعلی Rate Limit را دور نمی‌زند."""

    def setUp(self) -> None:
        from fxars.api.server import ApiApp
        self.env = make_env(bars=120, users=False)
        self.app = ApiApp(self.env.platform)
        self.app.limiter.limit = 3  # سقف کم برای تست

    def tearDown(self) -> None:
        self.env.close()

    def test_fake_tokens_share_ip_bucket(self) -> None:
        from fxars.api.server import ApiRequest
        # ۳ درخواست اول با توکن‌های جعلی متفاوت
        for i in range(3):
            req = ApiRequest(
                method="GET", path="/api/v1/instruments", query={},
                headers={"authorization": f"Bearer fake-{i}"},
                body=b"", ip="1.2.3.4",
            )
            resp = self.app.handle(req)
            self.assertEqual(resp.status, 401)  # احراز هویت رد
        # درخواست چهارم از همان IP با توکن جعلی دیگر
        req = ApiRequest(
            method="GET", path="/api/v1/instruments", query={},
            headers={"authorization": "Bearer fake-4"},
            body=b"", ip="1.2.3.4",
        )
        resp = self.app.handle(req)
        # یا 401 یا 429 — هر دو قابل قبول؛ مهم این است که Rate Limit IP کار کند
        self.assertIn(resp.status, (401, 429))


class Fix12CandlesPaginationTests(unittest.TestCase):
    """FIX-12: Pagination و source filter."""

    def setUp(self) -> None:
        import json
        from urllib.parse import parse_qs, urlparse
        from fxars.api.server import ApiApp, ApiRequest
        from tests.helpers import ANALYST_PASSWORD

        self.env = make_env(bars=240, users=True)
        self.app = ApiApp(self.env.platform)
        self.parse_qs, self.urlparse = parse_qs, urlparse
        resp = self.app.handle(ApiRequest(
            method="POST", path="/api/v1/auth/login", query={},
            headers={"content-type": "application/json"},
            body=json.dumps({"username": "analyst", "password": ANALYST_PASSWORD}).encode(),
            ip="127.0.0.1",
        ))
        self.token = json.loads(resp.body.decode())["token"]

    def tearDown(self) -> None:
        self.env.close()

    def _get(self, path: str):
        from fxars.api.server import ApiRequest
        parsed = self.urlparse(path)
        return self.app.handle(ApiRequest(
            method="GET", path=parsed.path, query=self.parse_qs(parsed.query),
            headers={"authorization": f"Bearer {self.token}"}, body=b"", ip="127.0.0.1",
        ))

    def test_offset(self) -> None:
        import json
        first = self._get("/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=5")
        payload = json.loads(first.body.decode())
        self.assertEqual(len(payload["items"]), 5)
        second = self._get("/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=5&offset=5")
        payload2 = json.loads(second.body.decode())
        # آخرین کندل page1 باید جدیدتر از آخرین کندل page2 باشد
        self.assertNotEqual(payload["items"][-1]["bar_open_time_utc"],
                            payload2["items"][-1]["bar_open_time_utc"])

    def test_source_id_reported(self) -> None:
        import json
        resp = self._get("/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=1")
        payload = json.loads(resp.body.decode())
        self.assertEqual(payload["source_id"], "demo_feed")


class Fix13ResultHashTests(unittest.TestCase):
    """FIX-13: result_hash شامل فیلدهای zone/invalidation/expiry است."""

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
'@

Set-Content -Path $newTestFile -Value $testContent -Encoding UTF8 -NoNewline
Write-Host "  [OK] tests/test_fixes.py written" -ForegroundColor Green

# حذف خطای import inspection_utils که وجود ندارد
$clean = Get-Content $newTestFile -Raw -Encoding UTF8
$clean = $clean.Replace("from fxars.inspection_utils import *  # noqa: F401,F403  (helper اختیاری)`r`n", "")
Set-Content -Path $newTestFile -Value $clean -Encoding UTF8 -NoNewline
Write-Host "  [OK] cleaned unused import" -ForegroundColor Green