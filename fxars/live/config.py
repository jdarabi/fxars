"""FIX-LIVE-CONFIG: پیکربندی daemon از فایل JSON."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_TIMEFRAMES = ["M15", "H1", "H4"]
DEFAULT_MINUTE_OFFSETS = [0, 15, 30, 45]
DEFAULT_ACTIVE_HOURS_UTC = list(range(24))
DEFAULT_ACTIVE_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


@dataclass
class ScheduleConfig:
    mode: str = "always"             # always | offsets | hours
    minute_offsets: list[int] = field(default_factory=lambda: list(DEFAULT_MINUTE_OFFSETS))
    active_hours_utc: list[int] = field(default_factory=lambda: list(DEFAULT_ACTIVE_HOURS_UTC))
    active_days: list[str] = field(default_factory=lambda: list(DEFAULT_ACTIVE_DAYS))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleConfig":
        data = data or {}
        return cls(
            mode=str(data.get("mode", "always")).lower(),
            minute_offsets=list(data.get("minute_offsets", DEFAULT_MINUTE_OFFSETS)),
            active_hours_utc=list(data.get("active_hours_utc", DEFAULT_ACTIVE_HOURS_UTC)),
            active_days=list(data.get("active_days", DEFAULT_ACTIVE_DAYS)),
        )

    def should_run(self, now) -> bool:
        """آیا الان باید تحلیل اجرا شود؟"""
        if self.mode == "always":
            return True
        day = now.strftime("%a")
        if day not in self.active_days:
            return False
        if now.hour not in self.active_hours_utc:
            return False
        if self.mode == "offsets":
            if now.minute not in self.minute_offsets:
                return False
        return True

    def next_run_hint(self, now) -> str:
        """توضیح انسانی برای زمان بعدی."""
        if self.mode == "always":
            return "always"
        return f"days={self.active_days}, hours={self.active_hours_utc[:3]}..., minutes={self.minute_offsets}"


@dataclass
class LiveConfig:
    instrument: str = "EURUSD"
    timeframes: list[str] = field(default_factory=lambda: list(DEFAULT_TIMEFRAMES))
    primary_timeframe: str = "H1"
    interval_seconds: int = 60
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    send_no_trade: bool = False
    max_signals_per_hour: int = 3
    history_bars: int = 500
    source_id: str = "mt5"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveConfig":
        data = data or {}
        return cls(
            instrument=str(data.get("instrument", "EURUSD")),
            timeframes=list(data.get("timeframes", DEFAULT_TIMEFRAMES)),
            primary_timeframe=str(data.get("primary_timeframe", "H1")),
            interval_seconds=int(data.get("interval_seconds", 60)),
            schedule=ScheduleConfig.from_dict(data.get("schedule", {})),
            send_no_trade=bool(data.get("send_no_trade", False)),
            max_signals_per_hour=int(data.get("max_signals_per_hour", 3)),
            history_bars=int(data.get("history_bars", 500)),
            source_id=str(data.get("source_id", "mt5")),
        )

    @classmethod
    def load(cls, path: str | Path) -> "LiveConfig":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument,
            "timeframes": list(self.timeframes),
            "primary_timeframe": self.primary_timeframe,
            "interval_seconds": self.interval_seconds,
            "schedule": {
                "mode": self.schedule.mode,
                "minute_offsets": list(self.schedule.minute_offsets),
                "active_hours_utc": list(self.schedule.active_hours_utc),
                "active_days": list(self.schedule.active_days),
            },
            "send_no_trade": self.send_no_trade,
            "max_signals_per_hour": self.max_signals_per_hour,
            "history_bars": self.history_bars,
            "source_id": self.source_id,
        }
