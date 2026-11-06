# C:\FX\fix_notifier_proxy.py
"""Rewrite fxars/live/notifier.py with proxy support + retry."""
from pathlib import Path
import shutil
import datetime

ROOT = Path(r'C:\FX')
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
BACKUP = ROOT / '.fix-backups' / f'notifier-proxy-{stamp}'
BACKUP.mkdir(parents=True, exist_ok=True)

path = ROOT / 'fxars/live/notifier.py'
if not path.exists():
    print('ERROR: notifier.py not found')
    raise SystemExit(1)

shutil.copy2(path, BACKUP / 'notifier.py')
print(f'Backup: {BACKUP / "notifier.py"}')

content = '''"""FIX-LIVE-02: ارسال هشدار به Telegram با پشتیبانی proxy."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

logger = logging.getLogger("fxars.live.telegram")


class TelegramError(RuntimeError):
    """ارسال به Telegram ناموفق بود."""


@dataclass
class TelegramConfig:
    token: str
    chat_id: str
    parse_mode: str = "HTML"
    disable_notification: bool = False
    timeout: float = 15.0
    proxy_url: str | None = None

    @classmethod
    def from_env(cls):
        token = os.environ.get("FXARS_TELEGRAM_TOKEN", "").strip()
        chat = os.environ.get("FXARS_TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat:
            return None
        proxy = (
            os.environ.get("FXARS_TELEGRAM_PROXY", "").strip()
            or os.environ.get("HTTPS_PROXY", "").strip()
            or os.environ.get("HTTP_PROXY", "").strip()
            or None
        )
        return cls(token=token, chat_id=chat, proxy_url=proxy)


class TelegramNotifier:
    """ارسال پیام به یک chat_id مشخص."""

    def __init__(self, config: TelegramConfig) -> None:
        try:
            import requests
        except ImportError as exc:
            raise TelegramError("requests نصب نیست. pip install requests") from exc
        self._requests = requests
        self.config = config
        self._base = f"https://api.telegram.org/bot{config.token}"
        self._proxies = None
        if config.proxy_url:
            self._proxies = {"http": config.proxy_url, "https": config.proxy_url}
            logger.info("telegram using proxy: %s", config.proxy_url)

    def _post(self, payload, *, retries: int = 3):
        for attempt in range(1, retries + 1):
            try:
                return self._requests.post(
                    f"{self._base}/sendMessage",
                    json=payload,
                    timeout=self.config.timeout,
                    proxies=self._proxies,
                )
            except self._requests.exceptions.ConnectionError as exc:
                logger.warning("telegram attempt %s/%s failed (network): %s",
                               attempt, retries, exc)
                if attempt == retries:
                    raise
            except self._requests.exceptions.Timeout as exc:
                logger.warning("telegram attempt %s/%s timed out: %s",
                               attempt, retries, exc)
                if attempt == retries:
                    raise

    def send_message(self, text, *, parse_mode=None, reply_markup=None,
                     disable_notification=None) -> bool:
        if not text.strip():
            logger.warning("empty message, skipped")
            return False
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": parse_mode or self.config.parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if disable_notification is not None:
            payload["disable_notification"] = disable_notification
        elif self.config.disable_notification:
            payload["disable_notification"] = True
        try:
            r = self._post(payload)
            if r.status_code != 200 or not r.json().get("ok"):
                logger.error("telegram send failed: status=%s body=%s",
                             r.status_code, r.text[:300])
                return False
            return True
        except Exception as exc:
            logger.error("telegram send aborted: %s", exc)
            return False

    def send_signal(self, decision, scenario=None) -> bool:
        return self.send_message(format_signal(decision, scenario))

    def send_no_trade(self, run_id: str, reason: str) -> bool:
        text = (
            "<b>FX-ARS</b> — NO TRADE\\n"
            f"run_id: <code>{run_id}</code>\\n"
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
    return "\\n".join(parts)


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
    return "\\n".join(lines)
'''

path.write_text(content, encoding='utf-8')
print(f'OK: {path} rewritten ({len(content)} bytes)')

import py_compile
try:
    py_compile.compile(str(path), doraise=True)
    print('syntax OK')
except py_compile.PyCompileError as exc:
    print('SYNTAX ERROR:', exc)
    raise SystemExit(1)