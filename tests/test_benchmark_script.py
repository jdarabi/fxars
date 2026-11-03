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
            self.assertEqual(result.returncode, 0, result.stderr[-500:])
            self.assertTrue((_P(tmp) / "benchmark.json").exists())
            self.assertTrue((_P(tmp) / "benchmark.md").exists())
            self.assertIn("Baseline", result.stdout)
            self.assertIn("Filtered", result.stdout)


if __name__ == "__main__":
    unittest.main()