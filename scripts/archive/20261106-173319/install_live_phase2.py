# C:\FX\install_live_phase2.py
"""Phase 2: Telegram notifier for FX-ARS Live."""
import datetime
import shutil
from pathlib import Path

ROOT = Path(r'C:\FX')
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
BACKUP = ROOT / '.fix-backups' / f'live-phase2-{stamp}'
BACKUP.mkdir(parents=True, exist_ok=True)


def backup(rel):
    src = ROOT / rel
    if not src.exists():
        return
    dst = BACKUP / rel.replace('\\', '__').replace('/', '__')
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def write_file(rel, content, marker=''):
    full = ROOT / rel
    if full.exists() and marker and marker in full.read_text(encoding='utf-8'):
        print(f'  [skip] {rel}')
        return
    if full.exists():
        backup(rel)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding='utf-8')
    print(f'  [wrote] {rel} ({len(content)} bytes)')


print('=== Phase 2: Telegram notifier ===')
print(f'Backup: {BACKUP}')

# ============================================================
# fxars/live/notifier.py
# ============================================================
write_file('fxars/live/notifier.py', '''"""FIX-LIVE-02: ارسال هشدار به Telegram.

نکات:
* Token و Chat ID از env (`FXARS_TELEGRAM_TOKEN`, `FXARS_TELEGRAM_CHAT_ID`).
* ارسال ساده با requests (sync).
* پیام‌ها با HTML format برای زیبایی.
* خطای شبکه مدیریت می‌شود (log می‌شود، daemon متوقف نمی‌شود).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger('fxars.live.telegram')


class TelegramError(RuntimeError):
    """ارسال به Telegram ناموفق بود."""


@dataclass
class TelegramConfig:
    token: str
    chat_id: str
    parse_mode: str = 'HTML'
    disable_notification: bool = False
    timeout: float = 10.0

    @classmethod
    def from_env(cls) -> 'TelegramConfig | None':
        token = os.environ.get('FXARS_TELEGRAM_TOKEN', '').strip()
        chat = os.environ.get('FXARS_TELEGRAM_CHAT_ID', '').strip()
        if not token or not chat:
            return None
        return cls(token=token, chat_id=chat)


class TelegramNotifier:
    """ارسال پیام به یک chat_id مشخص."""

    def __init__(self, config: TelegramConfig) -> None:
        try:
            import requests
        except ImportError as exc:
            raise TelegramError('requests نصب نیست. pip install requests') from exc
        self._requests = requests
        self.config = config
        self._base = f'https://api.telegram.org/bot{config.token}'

    def send_message(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
        disable_notification: bool | None = None,
    ) -> bool:
        if not text.strip():
            logger.warning('empty message, skipped')
            return False
        payload = {
            'chat_id': self.config.chat_id,
            'text': text,
            'parse_mode': parse_mode or self.config.parse_mode,
            'disable_web_page_preview': True,
        }
        if reply_markup is not None:
            payload['reply_markup'] = reply_markup
        if disable_notification is not None:
            payload['disable_notification'] = disable_notification
        elif self.config.disable_notification:
            payload['disable_notification'] = True
        try:
            r = self._requests.post(
                f'{self._base}/sendMessage',
                json=payload,
                timeout=self.config.timeout,
            )
            if r.status_code != 200 or not r.json().get('ok'):
                logger.error(
                    'telegram send failed: status=%s body=%s',
                    r.status_code, r.text[:300],
                )
                return False
            return True
        except Exception as exc:
            logger.exception('telegram request failed: %s', exc)
            return False

    def send_signal(self, decision: Any, scenario: Any | None = None) -> bool:
        """ارسال سیگنال با فرمت‌بندی فارسی."""
        text = format_signal(decision, scenario)
        return self.send_message(text)

    def send_no_trade(self, run_id: str, reason: str) -> bool:
        text = (
            f'<b>FX-ARS</b> — NO TRADE\n'
            f'run_id: <code>{run_id}</code>\n'
            f'reason: {reason}'
        )
        return self.send_message(text)


def _escape(value: Any) -> str:
    s = str(value)
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _fmt(value: Any) -> str:
    if value is None:
        return '—'
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, float):
        return f'{value:.4f}'
    return str(value)


def format_signal(decision: Any, scenario: Any | None = None) -> str:
    """ساخت پیام HTML برای یک سیگنال."""
    action = decision.action.value if hasattr(decision.action, 'value') else str(decision.action)
    direction = decision.direction.value if hasattr(decision.direction, 'value') else str(decision.direction)
    score = float(decision.score) if decision.score is not None else 0.0
    coverage = float(decision.coverage) if decision.coverage is not None else 0.0
    stability = float(decision.stability) if decision.stability is not None else 0.0
    family_scores = decision.family_scores or {}

    lines = [
        '<b>🚨 FX-ARS SIGNAL</b>',
        f'Action: <b>{_escape(action)}</b> | Direction: <b>{_escape(direction)}</b>',
        f'Score: {score:+.3f}  Coverage: {coverage:.0%}  Stability: {stability:.0%}',
    ]

    if family_scores:
        parts = ', '.join(f'{k}={v:+.2f}' for k, v in family_scores.items())
        lines.append(f'<i>Families</i>: {_escape(parts)}')

    if scenario is not None:
        lines.append('')
        lines.append('<b>📊 SCENARIO</b>')
        entry = scenario.entry_condition or {}
        stop_logic = scenario.stop_logic or {}
        targets = scenario.target_logic or ()
        lines.append(
            f'Entry: <b>{_escape(entry.get("type", "—"))}</b> @ '
            f'<code>{_escape(entry.get("level", "—"))}</code>'
        )
        lines.append(f'Stop : <code>{_escape(stop_logic.get("level", "—"))}</code>')
        for i, t in enumerate(targets[:2], start=1):
            lines.append(
                f'TP{i}  : <code>{_escape(t.get("price", "—"))}</code>'
                f' ({_escape(t.get("value", "—"))}R)'
            )
        exp = scenario.expiry_at
        if exp is not None:
            lines.append(f'Expiry: {_escape(exp.isoformat())}')

    lines.append('')
    lines.append('<i>— برای تأیید / رد، به داشبورد مراجعه کن —</i>')
    return '\n'.join(lines)


def format_account(info: dict[str, Any]) -> str:
    return (
        '<b>💼 FX-ARS ACCOUNT</b>\n'
        f'Login: <code>{_escape(info.get("login"))}</code>\n'
        f'Server: {_escape(info.get("server"))}\n'
        f'Currency: {_escape(info.get("currency"))}\n'
        f'Balance: <b>{_fmt(info.get("balance"))}</b>\n'
        f'Equity : <b>{_fmt(info.get("equity"))}</b>\n'
        f'Free Margin: {_fmt(info.get("margin_free"))}\n'
        f'Leverage: {_escape(info.get("leverage"))}'
    )
''', marker='FIX-LIVE-02')

# ============================================================
# tests/test_live_notifier.py
# ============================================================
write_file('tests/test_live_notifier.py', '''"""FIX-LIVE-02: Telegram notifier tests."""
from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.live.notifier import (
    TelegramConfig,
    TelegramNotifier,
    format_account,
    format_signal,
)


@dataclass
class _FakeDecision:
    action: str
    direction: str
    score: float
    coverage: float
    stability: float
    family_scores: dict


@dataclass
class _FakeScenario:
    entry_condition: dict
    stop_logic: dict
    target_logic: tuple
    expiry_at: object


class FormatTests(unittest.TestCase):
    def test_format_signal_basic(self):
        decision = _FakeDecision(
            action='LONG', direction='LONG',
            score=0.42, coverage=0.43, stability=1.0,
            family_scores={'STRUCTURE': 0.12, 'TREND': 0.09},
        )
        scenario = _FakeScenario(
            entry_condition={'type': 'price_cross_above', 'level': '1.08700'},
            stop_logic={'level': '1.08200'},
            target_logic=(
                {'price': '1.09450', 'value': 1.5},
                {'price': '1.10200', 'value': 3.0},
            ),
            expiry_at=None,
        )
        text = format_signal(decision, scenario)
        self.assertIn('LONG', text)
        self.assertIn('1.08700', text)
        self.assertIn('1.08200', text)
        self.assertIn('1.09450', text)
        self.assertIn('+0.420', text)

    def test_format_account(self):
        info = {
            'login': 53247702, 'server': 'Alpari-MT5-Demo',
            'currency': 'USD', 'balance': 100000.0, 'equity': 100000.0,
            'margin_free': 100000.0, 'leverage': 100,
        }
        text = format_account(info)
        self.assertIn('53247702', text)
        self.assertIn('100000', text)


class ConfigTests(unittest.TestCase):
    def test_from_env_empty(self):
        import os
        old_token = os.environ.pop('FXARS_TELEGRAM_TOKEN', None)
        old_chat = os.environ.pop('FXARS_TELEGRAM_CHAT_ID', None)
        try:
            cfg = TelegramConfig.from_env()
            self.assertIsNone(cfg)
        finally:
            if old_token is not None:
                os.environ['FXARS_TELEGRAM_TOKEN'] = old_token
            if old_chat is not None:
                os.environ['FXARS_TELEGRAM_CHAT_ID'] = old_chat

    def test_from_env_ok(self):
        import os
        os.environ['FXARS_TELEGRAM_TOKEN'] = 'abc:123'
        os.environ['FXARS_TELEGRAM_CHAT_ID'] = '42'
        try:
            cfg = TelegramConfig.from_env()
            self.assertIsNotNone(cfg)
            self.assertEqual(cfg.token, 'abc:123')
            self.assertEqual(cfg.chat_id, '42')
        finally:
            os.environ.pop('FXARS_TELEGRAM_TOKEN', None)
            os.environ.pop('FXARS_TELEGRAM_CHAT_ID', None)


class NotifierLiveTests(unittest.TestCase):
    """تست واقعی ارسال — فقط اگر token + chat set شده باشند."""

    @classmethod
    def setUpClass(cls):
        cfg = TelegramConfig.from_env()
        if cfg is None:
            raise unittest.SkipTest('FXARS_TELEGRAM_TOKEN / CHAT_ID not set')
        try:
            cls.notifier = TelegramNotifier(cfg)
        except Exception as exc:
            raise unittest.SkipTest(f'telegram unavailable: {exc}')

    def test_send_simple(self):
        ok = self.notifier.send_message('FX-ARS test from unit test')
        self.assertTrue(ok, 'telegram send failed')

    def test_send_signal(self):
        decision = _FakeDecision(
            action='LONG', direction='LONG',
            score=0.42, coverage=0.43, stability=1.0,
            family_scores={'STRUCTURE': 0.12},
        )
        scenario = _FakeScenario(
            entry_condition={'type': 'price_cross_above', 'level': '1.08700'},
            stop_logic={'level': '1.08200'},
            target_logic=({'price': '1.09450', 'value': 1.5},),
            expiry_at=None,
        )
        ok = self.notifier.send_signal(decision, scenario)
        self.assertTrue(ok)


if __name__ == '__main__':
    unittest.main()
''', marker='FIX-LIVE-02')

print()
print('=== Phase 2 done ===')
print()
print('Set environment variables:')
print('  $env:FXARS_TELEGRAM_TOKEN = "1234567890:ABC..."')
print('  $env:FXARS_TELEGRAM_CHAT_ID = "987654321"')
print()
print('Then test:')
print('  python -m unittest tests.test_live_notifier -v')
