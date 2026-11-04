"""FIX-LIVE-02: Telegram notifier با urllib (سازگار با VPN/SSL ویندوز)."""
from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger("fxars.live.telegram")


class TelegramError(RuntimeError):
    """ارسال به Telegram ناموفق بود."""


@dataclass
class TelegramConfig:
    token: str
    chat_id: str
    parse_mode: str = "HTML"
    disable_notification: bool = False
    timeout: float = 30.0

    @classmethod
    def from_env(cls):
        token = os.environ.get("FXARS_TELEGRAM_TOKEN", "").strip()
        chat = os.environ.get("FXARS_TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat:
            return None
        return cls(token=token, chat_id=chat)


class TelegramNotifier:
    """ارسال پیام با urllib (بدون requests)."""

    def __init__(self, config: TelegramConfig) -> None:
        self.config = config
        self._base = f"https://api.telegram.org/bot{config.token}"
        self._ssl_ctx = ssl.create_default_context()
        try:
            import certifi
            self._ssl_ctx.load_verify_locations(certifi.where())
            logger.info("using certifi CA bundle")
        except ImportError:
            logger.info("certifi not installed; using system CA")

    def _post_json(self, url: str, payload: dict, *, retries: int = 3) -> dict:
        body = json.dumps(payload).encode("utf-8")
        last_exc = None
        for attempt in range(1, retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "FX-ARS/1.4.12",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(
                    req, timeout=self.config.timeout, context=self._ssl_ctx,
                ) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_exc = exc
                logger.warning(
                    "telegram attempt %s/%s failed: %s", attempt, retries, exc,
                )
                if attempt == retries:
                    raise
        if last_exc is not None:
            raise last_exc
        return {}

    def send_message(self, text, *, parse_mode=None, disable_notification=None) -> bool:
        if not text.strip():
            logger.warning("empty message, skipped")
            return False
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": parse_mode or self.config.parse_mode,
            "disable_web_page_preview": True,
        }
        if disable_notification is not None:
            payload["disable_notification"] = disable_notification
        elif self.config.disable_notification:
            payload["disable_notification"] = True
        try:
            data = self._post_json(f"{self._base}/sendMessage", payload)
        except Exception as exc:
            logger.error("telegram send aborted: %s", exc)
            return False
        if not data.get("ok"):
            logger.error("telegram send failed: %s", str(data)[:300])
            return False
        return True

    def send_signal(self, decision, scenario=None) -> bool:
        return self.send_message(format_signal(decision, scenario))

    def send_no_trade(self, run_id: str, reason: str) -> bool:
        text = (
            "<b>FX-ARS</b> — NO TRADE\n"
            f"run_id: <code>{run_id}</code>\n"
            f"reason: {reason}"
        )
        return self.send_message(text)


def _escape(value) -> str:
    s = str(value)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def format_signal(decision, scenario=None) -> str:
    action = decision.action.value if hasattr(decision.action, "value") else str(decision.action)
    direction = decision.direction.value if hasattr(decision.direction, "value") else str(decision.direction)
    score = float(decision.score) if decision.score is not None else 0.0
    coverage = float(decision.coverage) if decision.coverage is not None else 0.0
    stability = float(decision.stability) if decision.stability is not None else 0.0
    family_scores = decision.family_scores or {}

    parts = [
        "<b>🚨 FX-ARS SIGNAL</b>",
        f"Action: <b>{_escape(action)}</b> | Direction: <b>{_escape(direction)}</b>",
        f"Score: {score:+.3f}  Coverage: {coverage:.0%}  Stability: {stability:.0%}",
    ]
    if family_scores:
        joined = ", ".join(f"{k}={v:+.2f}" for k, v in family_scores.items())
        parts.append(f"<i>Families</i>: {_escape(joined)}")
    if scenario is not None:
        parts.append("")
        parts.append("<b>📊 SCENARIO</b>")
        entry = scenario.entry_condition or {}
        stop_logic = scenario.stop_logic or {}
        targets = scenario.target_logic or ()
        parts.append(
            f"Entry: <b>{_escape(entry.get('type', '—'))}</b> "
            f"@ <code>{_escape(entry.get('level', '—'))}</code>"
        )
        parts.append(f"Stop : <code>{_escape(stop_logic.get('level', '—'))}</code>")
        for i, t in enumerate(targets[:2], start=1):
            parts.append(
                f"TP{i}  : <code>{_escape(t.get('price', '—'))}</code> "
                f"({_escape(t.get('value', '—'))}R)"
            )
        exp = scenario.expiry_at
        if exp is not None:
            parts.append(f"Expiry: {_escape(exp.isoformat())}")
    parts.append("")
    parts.append("<i>— برای تأیید / رد، به داشبورد مراجعه کن —</i>")
    return "\n".join(parts)


def format_account(info) -> str:
    lines = [
        "<b>💼 FX-ARS ACCOUNT</b>",
        f"Login: <code>{_escape(info.get('login'))}</code>",
        f"Server: {_escape(info.get('server'))}",
        f"Currency: {_escape(info.get('currency'))}",
        f"Balance: <b>{_fmt(info.get('balance'))}</b>",
        f"Equity : <b>{_fmt(info.get('equity'))}</b>",
        f"Free Margin: {_fmt(info.get('margin_free'))}",
        f"Leverage: {_escape(info.get('leverage'))}",
    ]
    return "\n".join(lines)
