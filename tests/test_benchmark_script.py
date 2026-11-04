"""Benchmark script smoke test (P3-5)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path as _P

_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class BenchmarkScriptTests(unittest.TestCase):
    def test_script_runs_and_outputs(self):
        """اسکریپت باید اجرا شود و گزارش بسازد.

        نکته: خروجی می‌تواند 0 (OK) یا 1 (regression) باشد. در هر دو حالت
        اسکریپت اجرا شده و گزارش‌ها ساخته شده‌اند. regression guard
        خودش بخشی از پروتکل اعتبارسنجی است، نه خطای تست.
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable, "scripts/benchmark_regime.py",
                    "--instrument", "EURUSD",
                    "--timeframe", "H1",
                    "--out-dir", tmp,
                    "--no-fail-on-regression",  # FIX-BENCH
                ],
                cwd=_ROOT,
                capture_output=True,
                text=True,
                timeout=300,
            )
            self.assertEqual(
                result.returncode, 0,
                f"stdout={result.stdout[-500:]}\nstderr={result.stderr[-500:]}",
            )
            self.assertTrue((_P(tmp) / "benchmark.json").exists())
            self.assertTrue((_P(tmp) / "benchmark.md").exists())
            self.assertIn("Baseline", result.stdout)
            self.assertIn("Filtered", result.stdout)

    def test_script_regression_exit_code_is_allowed(self):
        """اگر regression بود، returncode=1 قابل قبول است (نه شکست)."""
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable, "scripts/benchmark_regime.py",
                    "--instrument", "EURUSD",
                    "--timeframe", "H1",
                    "--out-dir", tmp,
                ],
                cwd=_ROOT,
                capture_output=True,
                text=True,
                timeout=300,
            )
            # 0 = OK, 1 = regression detected — هر دو معتبر
            self.assertIn(
                result.returncode, (0, 1),
                f"unexpected exit code: {result.returncode}\n"
                f"stdout={result.stdout[-500:]}\nstderr={result.stderr[-500:]}",
            )
            # گزارش‌ها در هر دو حالت ساخته می‌شوند
            self.assertTrue((_P(tmp) / "benchmark.json").exists())
            self.assertTrue((_P(tmp) / "benchmark.md").exists())
            self.assertIn("Baseline", result.stdout)
            self.assertIn("Filtered", result.stdout)


if __name__ == "__main__":
    unittest.main()
