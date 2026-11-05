"""Windows desktop notifications via winotify or PowerShell BurntToast."""
from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("fxars.live.desktop")


@dataclass
class DesktopConfig:
    app_name: str = "FX-ARS"
    duration: str = "long"
    sound: bool = True

    @classmethod
    def from_env(cls) -> "DesktopConfig":
        return cls()


class DesktopNotifier:
    """Windows toast notifications (no required external deps)."""

    def __init__(self, config: DesktopConfig | None = None) -> None:
        self.config = config or DesktopConfig()
        self._method = self._detect_method()
        logger.info("Desktop notifier method: %s", self._method)

    def _detect_method(self) -> str:
        if sys.platform != "win32":
            return "none"
        try:
            import winotify  # noqa: F401
            return "winotify"
        except ImportError:
            pass
        try:
            r = subprocess.run(
                ["powershell", "-Command", "Get-Command New-BurntToastNotification -ErrorAction SilentlyContinue"],
                capture_output=True, timeout=5, text=True,
            )
            if r.returncode == 0 and r.stdout.strip():
                return "burnttoast"
        except Exception:
            pass
        return "powershell"

    def send(self, title: str, message: str, *, urgent: bool = False) -> bool:
        if self._method == "none":
            logger.warning("Desktop notifications not available (non-Windows)")
            return False
        try:
            if self._method == "winotify":
                return self._send_winotify(title, message, urgent)
            if self._method == "burnttoast":
                return self._send_burnttoast(title, message)
            if self._method == "powershell":
                return self._send_powershell(title, message)
        except Exception as exc:
            logger.error("desktop notification failed: %s", exc)
        return False

    def _send_winotify(self, title: str, message: str, urgent: bool) -> bool:
        from winotify import Notification, audio
        toast = Notification(
            app_id=self.config.app_name, title=title, msg=message,
            duration="long" if urgent else self.config.duration,
        )
        if urgent:
            toast.set_audio(audio.LoopingAlarm, loop=False)
        elif self.config.sound:
            toast.set_audio(audio.Default, loop=False)
        toast.show()
        return True

    def _send_burnttoast(self, title: str, message: str) -> bool:
        title_esc = title.replace("'", "''")
        msg_esc = message.replace("'", "''")
        ps = f"New-BurntToastNotification -Text '{title_esc}', '{msg_esc}'"
        r = subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=10, text=True)
        return r.returncode == 0

    def _send_powershell(self, title: str, message: str) -> bool:
        title_esc = title.replace("'", "''")
        msg_esc = message.replace("'", "''")
        ps = f"""
$ErrorActionPreference = 'SilentlyContinue'
try {{
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
  $tmpl = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
  $texts = $tmpl.GetElementsByTagName('text')
  $texts.Item(0).AppendChild($tmpl.CreateTextNode('{title_esc}')) | Out-Null
  $texts.Item(1).AppendChild($tmpl.CreateTextNode('{msg_esc}')) | Out-Null
  $toast = [Windows.UI.Notifications.ToastNotification]::new($tmpl)
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{self.config.app_name}').Show($toast)
}} catch {{ exit 1 }}
"""
        r = subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=10, text=True)
        return r.returncode == 0

    def send_signal(self, decision: Any, scenario: Any | None, symbol: str | None = None, timeframe: str | None = None) -> bool:
        action = decision.action.value if hasattr(decision.action, "value") else str(decision.action)
        emoji = {"LONG": "🟢", "SHORT": "🔴", "NO_TRADE": "⚪"}.get(action, "⚪")
        title = f"{emoji} {symbol or '?'} {timeframe or '?'} — {action}"

        lines = [f"Score: {float(decision.score):+.3f}"]
        if scenario is not None:
            entry = (scenario.entry_condition or {}).get("level", "—")
            stop = (scenario.stop_logic or {}).get("level", "—")
            lines.append(f"Entry: {entry}")
            lines.append(f"Stop: {stop}")
            targets = scenario.target_logic or ()
            if targets:
                lines.append(f"TP1: {targets[0].get('price', '—')}")
                if len(targets) > 1:
                    lines.append(f"TP2: {targets[1].get('price', '—')}")
        return self.send(title, "\n".join(lines), urgent=(action in ("LONG", "SHORT")))

    def send_advice(self, advice: Any) -> bool:
        emoji = {
            "BUY": "🟢", "SELL": "🔴", "HOLD": "🟡",
            "EXIT": "🟠", "STAY_OUT": "⚪", "WAIT": "🔵",
        }.get(advice.action.value, "⚪")
        title = f"{emoji} {advice.symbol} {advice.timeframe} — {advice.action.value}"
        lines = [
            advice.reason,
            f"Confidence: {advice.confidence:.0%}",
        ]
        if advice.suggestions:
            lines.append("")
            lines.append("• " + "\n• ".join(advice.suggestions[:3]))
        return self.send(title, "\n".join(lines), urgent=(advice.action.value in ("BUY", "SELL", "EXIT")))

    def test(self) -> bool:
        return self.send(
            "FX-ARS — Test",
            "Desktop notification is working!",
            urgent=False,
        )