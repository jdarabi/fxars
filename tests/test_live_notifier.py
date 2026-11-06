"""FIX-LIVE-02: Telegram notifier tests."""
from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
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
