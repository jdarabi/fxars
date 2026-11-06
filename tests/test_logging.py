"""Structured logging tests."""
from __future__ import annotations

import io
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fxars.core.logging_setup import (
    ErrorFileHandler,
    JsonFormatter,
    _redact,
    _redact_string,
    configure_logging,
    get_logger,
)


class RedactionTests(unittest.TestCase):
    def test_dict_keys_redacted(self):
        data = {"password": "secret123", "user": "alice"}
        redacted = _redact(data)
        self.assertEqual(redacted["password"], "***")
        self.assertEqual(redacted["user"], "alice")

    def test_bearer_token_in_string(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = _redact_string(text)
        self.assertIn("***", result)
        self.assertNotIn("eyJhbGci", result)

    def test_long_hex_token(self):
        token = "a" * 40
        result = _redact_string("Token: " + token)
        self.assertNotIn(token, result)

    def test_nested_redaction(self):
        data = {"outer": {"token": "abc", "nested": {"secret": "xyz", "ok": 1}}}
        redacted = _redact(data)
        self.assertEqual(redacted["outer"]["token"], "***")
        self.assertEqual(redacted["outer"]["nested"]["secret"], "***")
        self.assertEqual(redacted["outer"]["nested"]["ok"], 1)

    def test_list_redaction(self):
        data = [{"api_key": "k1"}, {"api_key": "k2"}]
        redacted = _redact(data)
        for item in redacted:
            self.assertEqual(item["api_key"], "***")


class FormatterTests(unittest.TestCase):
    def test_emits_valid_json(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            "fxars.test", logging.INFO, "test.py", 10, "hello %s", ("world",), None,
        )
        payload = json.loads(formatter.format(record))
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["message"], "hello world")
        self.assertIn("correlation_id", payload)
        self.assertIn("ts", payload)

    def test_extra_data_redacted(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            "fxars.test", logging.INFO, "test.py", 10, "msg", (), None,
        )
        record.data = {"password": "abc", "ok": 1}
        payload = json.loads(formatter.format(record))
        self.assertEqual(payload["data"]["password"], "***")
        self.assertEqual(payload["data"]["ok"], 1)


class ConfigureLoggingTests(unittest.TestCase):
    def test_stream_handler_works(self):
        buffer = io.StringIO()
        configure_logging("INFO", stream=buffer)
        logger = get_logger("test_stream")
        logger.info("hello")
        output = buffer.getvalue().strip()
        self.assertTrue(output)
        payload = json.loads(output)
        self.assertEqual(payload["message"], "hello")

    def test_error_file_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = _P(tmp) / "errors.jsonl"
            configure_logging("INFO", error_log_path=log_path)
            logger = get_logger("test_file")
            logger.error("an error")
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("an error", content)

    def test_error_handler_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = _P(tmp) / "errors.jsonl"
            handler = ErrorFileHandler(log_path, max_lines=3)
            root = logging.getLogger("fxars.rotation_test")
            root.addHandler(handler)
            root.setLevel(logging.ERROR)
            root.propagate = False
            for i in range(5):
                root.error("error %d", i)
            lines = log_path.read_text(encoding="utf-8").strip().split("\n")
            self.assertLessEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()
