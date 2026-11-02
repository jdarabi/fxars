"""P0/P1 regression tests for critical fixes."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json
import unittest
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from fxars.api.server import ApiApp, ApiRequest
from fxars.core.errors import (
    AuthenticationError,
    PhaseViolationError,
    RateLimitedError,
)
from fxars.domain.enums import Role
from fxars.domain.models import Candle, EconomicEvent
from tests.helpers import ANALYST_PASSWORD, make_env


class EconomicEventTimeInvariantTests(unittest.TestCase):
    def test_available_before_event_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            EconomicEvent(
                event_id="e1", indicator="X", currency="USD", country="US",
                event_time="2026-10-30T12:00:00Z", published_at=None,
                available_at="2026-10-30T11:00:00Z", importance="HIGH",
            )
        self.assertIn("event_time", str(ctx.exception))

    def test_available_before_published_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            EconomicEvent(
                event_id="e2", indicator="X", currency="USD", country="US",
                event_time="2026-10-30T10:00:00Z", published_at="2026-10-30T12:00:00Z",
                available_at="2026-10-30T11:00:00Z", importance="HIGH",
            )
        self.assertIn("published_at", str(ctx.exception))

    def test_valid_event_accepted(self):
        event = EconomicEvent(
            event_id="e3", indicator="X", currency="USD", country="US",
            event_time="2026-10-30T10:00:00Z", published_at="2026-10-30T10:00:30Z",
            available_at="2026-10-30T10:02:00Z", importance="HIGH",
        )
        self.assertEqual(event.currency, "USD")

    def test_event_without_published_at_accepted(self):
        event = EconomicEvent(
            event_id="e4", indicator="X", currency="USD", country="US",
            event_time="2026-10-30T10:00:00Z", published_at=None,
            available_at="2026-10-30T10:00:00Z", importance="HIGH",
        )
        self.assertIsNone(event.published_at)


class ClosedCandleAvailabilityTests(unittest.TestCase):
    def test_closed_candle_available_before_close_is_suspect(self):
        from fxars.data.validation import CandleValidator

        env = make_env(bars=120)
        try:
            base = env.candles[50]
            broken = Candle(
                instrument_id=base.instrument_id,
                source_id=base.source_id,
                timeframe=base.timeframe,
                open_time=base.open_time,
                open=base.open,
                high=base.high,
                low=base.low,
                close=base.close,
                ingested_at=base.ingested_at,
                available_at=base.open_time,
                is_closed=True,
                spread=base.spread,
                tick_volume=base.tick_volume,
            )
            assessment = CandleValidator(env.instrument).assess(broken)
            self.assertIn("available_at_before_close", assessment.flags)
        finally:
            env.close()


class SessionRevocationTests(unittest.TestCase):
    def setUp(self):
        self.env = make_env(bars=100, users=True)

    def tearDown(self):
        self.env.close()

    def test_password_change_revokes_sessions(self):
        identity = self.env.platform.identity
        login = identity.login("analyst", ANALYST_PASSWORD)
        self.assertIsNotNone(identity.resolve_session(login.token))
        user = self.env.platform.users.get_by_username("analyst")
        identity.set_password(user.user_id, "NewAnalystPass123!", actor="admin")
        self.assertIsNone(identity.resolve_session(login.token))

    def test_new_password_can_login(self):
        identity = self.env.platform.identity
        user = self.env.platform.users.get_by_username("analyst")
        identity.set_password(user.user_id, "NewAnalystPass123!", actor="admin")
        result = identity.login("analyst", "NewAnalystPass123!")
        self.assertIsNotNone(identity.resolve_session(result.token))


class BacktestPendingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.env = make_env(bars=500)

    def tearDown(self):
        self.env.close()

    def test_backtest_completes_with_consistent_stats(self):
        result = self.env.platform.research.run("EURUSD", "H1", persist=False)
        self.assertIn("trade_count", result.run.metrics)
        stats = result.run.metrics.get("stats", {})
        self.assertIn("pending_expired", stats)
        self.assertIn("pending_invalidated", stats)
        self.assertIn("entries", stats)

    def test_entry_never_before_decision(self):
        result = self.env.platform.research.run("EURUSD", "H1", persist=False)
        for trade in result.run.trades:
            self.assertLessEqual(trade["entry_time"], trade["exit_time"])


class KillSwitchAtSubmitTests(unittest.TestCase):
    def setUp(self):
        self.env = make_env(bars=120)

    def tearDown(self):
        self.env.close()

    def test_submit_raises_when_phase_readonly(self):
        with self.assertRaises(PhaseViolationError):
            self.env.platform.execution.submit(
                "oi_missing", price=Decimal("1.0850"), pip_size=Decimal("0.0001"),
            )

    def test_killswitch_assert_inactive_blocks(self):
        from fxars.core.errors import KillSwitchActiveError

        self.env.platform.killswitch.activate(actor="tester", reason="unit test")
        with self.assertRaises(KillSwitchActiveError):
            self.env.platform.killswitch.assert_inactive()


class PrimarySourceCorrelationTests(unittest.TestCase):
    def setUp(self):
        self.env = make_env(bars=240)

    def tearDown(self):
        self.env.close()

    def test_correlation_uses_primary_source(self):
        service = self.env.platform.risk
        corr = service._correlations(
            "EURUSD", ["EURUSD", "DXY"], "H1", self.env.as_of,
        )
        self.assertIn("EURUSD", corr)
        self.assertEqual(corr["EURUSD"], 1.0)
        self.assertIn("DXY", corr)
        self.assertIsInstance(corr["DXY"], float)
        self.assertGreaterEqual(corr["DXY"], -1.0)
        self.assertLessEqual(corr["DXY"], 1.0)


class IdempotentReplayTests(unittest.TestCase):
    def setUp(self):
        self.env = make_env(bars=400)

    def tearDown(self):
        self.env.close()

    def test_identical_replay_has_single_audit(self):
        first = self.env.analyze()
        audit_before = self.env.platform.audit_repo.count()
        outbox_before = self.env.platform.outbox.pending_count

        second = self.env.analyze()
        self.assertEqual(first.run.run_id, second.run.run_id)
        self.assertEqual(first.run.result_hash, second.run.result_hash)

        self.assertEqual(
            audit_before, self.env.platform.audit_repo.count(),
            "replay must not append new audit events",
        )
        self.assertEqual(
            outbox_before, self.env.platform.outbox.pending_count,
            "replay must not emit new outbox events",
        )

    def test_replay_returns_stored_evidence(self):
        first = self.env.analyze()
        second = self.env.analyze()
        self.assertEqual(
            sorted(e.evidence_id for e in first.evidences),
            sorted(e.evidence_id for e in second.evidences),
        )


class ConsecutiveLoginFailureTests(unittest.TestCase):
    def setUp(self):
        self.env = make_env(bars=100, users=True)

    def tearDown(self):
        self.env.close()

    def test_success_resets_failure_counter(self):
        identity = self.env.platform.identity
        limit = self.env.settings.security.login_max_attempts

        for _ in range(3):
            with self.assertRaises(AuthenticationError):
                identity.login("analyst", "wrong-password")

        identity.login("analyst", ANALYST_PASSWORD)

        for _ in range(limit - 1):
            with self.assertRaises(AuthenticationError):
                identity.login("analyst", "wrong-password")

        with self.assertRaises(AuthenticationError):
            identity.login("analyst", "wrong-password")

        with self.assertRaises(RateLimitedError):
            identity.login("analyst", "wrong-password")


class PaginationOrderTests(unittest.TestCase):
    def _call(self, token: str, query: str) -> dict:
        app = ApiApp(self.env.platform)
        parsed = urlparse(query)
        req = ApiRequest(
            method="GET", path=parsed.path, query=parse_qs(parsed.query),
            headers={"authorization": f"Bearer {token}"}, body=b"", ip="127.0.0.1",
        )
        resp = app.handle(req)
        self.assertEqual(resp.status, 200, resp.body.decode()[:200])
        return json.loads(resp.body.decode())

    def setUp(self):
        self.env = make_env(bars=120)
        self.env.platform.identity.create_user(
            "pguser", Role.ANALYST, "PgTestPass123!",
        )
        self.token = self.env.platform.identity.login(
            "pguser", "PgTestPass123!",
        ).token

    def tearDown(self):
        self.env.close()

    def test_order_asc_accepted(self):
        body = self._call(
            self.token,
            "/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=3&order=asc",
        )
        self.assertEqual(body.get("order"), "asc")
        self.assertLessEqual(len(body["items"]), 3)

    def test_order_desc_default(self):
        body = self._call(
            self.token,
            "/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=3",
        )
        self.assertEqual(body.get("order"), "desc")

    def test_order_asc_offset_walks_forward(self):
        page1 = self._call(
            self.token,
            "/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=3&order=asc",
        )
        page2 = self._call(
            self.token,
            "/api/v1/market-data/candles?instrument_id=EURUSD&timeframe=H1&limit=3&order=asc&offset=3",
        )
        self.assertNotEqual(
            page1["items"][-1]["bar_open_time_utc"],
            page2["items"][-1]["bar_open_time_utc"],
        )


class ReadOnlyPhaseGuardTests(unittest.TestCase):
    def setUp(self):
        self.env = make_env(bars=120)

    def tearDown(self):
        self.env.close()

    def test_create_intent_blocked_in_readonly(self):
        with self.assertRaises(PhaseViolationError):
            self.env.platform.execution.create_intent("sc_missing")


if __name__ == "__main__":
    unittest.main()