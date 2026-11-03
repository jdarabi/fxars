"""ابزار مشترک آزمون‌ها: پلتفرم درون‌حافظه‌ای با داده قطعی."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fxars.config.settings import Settings
from fxars.data.synthetic import generate_candles, generate_reference_candles
from fxars.domain.enums import Role
from fxars.instruments.calendar import TradingCalendar, default_holidays
from fxars.platform import Platform
from fxars.storage.db import Database

UTC = timezone.utc
ANALYST_PASSWORD = "AnalystPass123!"
ADMIN_PASSWORD = "AdminPass12345!"
AUDITOR_PASSWORD = "AuditorPass123!"


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def set(self, moment: datetime) -> None:
        self.moment = moment

    def advance(self, seconds: int) -> None:
        self.moment = self.moment + timedelta(seconds=seconds)


class TestEnv:
    def __init__(
        self,
        *,
        bars: int = 800,
        users: bool = False,
        environment: str = "dev",
        phase: str = "READ_ONLY",
    ) -> None:
        self.settings = Settings.from_dict({
            "phase": phase,
            "db_path": ":memory:",
            "environment": environment,
        })
        self.calendar = TradingCalendar(default_holidays())
        start = datetime(2026, 2, 1, 22, 0, tzinfo=UTC)
        self.clock = Clock(start)
        self.platform = Platform(self.settings, db=Database(":memory:"), clock=self.clock, calendar=self.calendar)
        self.platform.bootstrap(create_users=False)
        self.instrument = self.platform.instruments.get("EURUSD")
        self.candles = generate_candles(self.instrument, start, bars, seed=21, calendar=self.calendar)
        self.clock.set(self.candles[-1].available_at)
        self.platform.ingestion.ingest(
            self.candles, instrument_id="EURUSD", source_id="demo_feed", now=self.clock(),
        )
        reference = generate_reference_candles(self.candles, self.platform.instruments.get("DXY"), seed=31)
        self.platform.ingestion.ingest(reference, instrument_id="DXY", source_id="demo_ref", now=self.clock())
        self.as_of = self.candles[-1].available_at
        if users:
            self.create_users()

    def create_users(self) -> None:
        self.platform.identity.create_user("analyst", Role.ANALYST, ANALYST_PASSWORD)
        self.platform.identity.create_user("auditor", Role.AUDITOR, AUDITOR_PASSWORD)
        self.platform.identity.create_user("admin", Role.ADMIN, ADMIN_PASSWORD, totp_enabled=True)

    def analyze(self, **kwargs):
        return self.platform.run_analysis(
            "EURUSD", "H1", as_of=kwargs.pop("as_of", self.as_of), **kwargs
        )

    def close(self) -> None:
        self.platform.close()


def make_env(
    *,
    bars: int = 800,
    users: bool = False,
    environment: str = "dev",
    phase: str = "READ_ONLY",
) -> TestEnv:
    return TestEnv(bars=bars, users=users, environment=environment, phase=phase)