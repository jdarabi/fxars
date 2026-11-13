"""FIX-DESKTOP-NOTIFY: نوتیف دسکتاپ ویندوز برای سیگنالها."""
from __future__ import annotations

import logging

logger = logging.getLogger("fxars.live.desktop_notify")


class DesktopNotifier:
    """نوتیف دسکتاپ با plyer یا win10toast (fallback)."""

    def __init__(self, *, enabled: bool = True, app_name: str = "FX-ARS", timeout: int = 8) -> None:
        self.enabled = enabled
        self.app_name = app_name
        self.timeout = timeout
        self._backend = self._detect_backend()
        if self._backend is None and enabled:
            logger.warning("هیچ backend نوتیف دسکتاپ پیدا نشد (plyer/win10toast نصب نیست)")

    @staticmethod
    def _detect_backend():
        try:
            from plyer import notification  # noqa: F401
            return "plyer"
        except ImportError:
            pass
        try:
            from win10toast import ToastNotifier  # noqa: F401
            return "win10toast"
        except ImportError:
            pass
        return None

    def is_available(self) -> bool:
        return self._backend is not None

    def send(self, title: str, message: str, *, timeout: int | None = None) -> bool:
        if not self.enabled:
            return False
        if self._backend is None:
            return False
        timeout = timeout if timeout is not None else self.timeout
        try:
            if self._backend == "plyer":
                from plyer import notification
                notification.notify(
                    title=title,
                    message=message,
                    app_name=self.app_name,
                    timeout=timeout,
                )
                return True
            if self._backend == "win10toast":
                from win10toast import ToastNotifier
                ToastNotifier().show_toast(
                    title, message, duration=timeout, threaded=True,
                )
                return True
        except Exception as exc:
            logger.warning("desktop notify failed: %s", exc)
        return False

    def send_signal(self, instrument: str, timeframe: str, action: str, score: float,
                    scenario_id: str | None = None) -> bool:
        title = f"FX-ARS  {action} {instrument}"
        lines = [
            f"نماد: {instrument} / {timeframe}",
            f"جهت: {action}",
            f"امتیاز: {score:+.3f}",
        ]
        if scenario_id:
            lines.append(f"سناریو: {scenario_id}")
        return self.send(title, "\n".join(lines))
