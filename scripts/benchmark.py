"""Benchmark سبک: داده دمو، زمان Ingestion و AnalysisRun."""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fxars.platform import Platform


def main() -> int:
    platform = Platform()
    platform.bootstrap(create_users=False)
    samples: list[float] = []
    for _ in range(3):
        start = time.perf_counter()
        result = platform.run_analysis("EURUSD", "H1")
        elapsed = time.perf_counter() - start
        samples.append(elapsed)
        print(f"run={result.run.run_id} bars={result.run.data_quality.get('bars')} evidence={len(result.evidences)} "
              f"time={elapsed:.3f}s")
    print(f"P50={statistics.median(samples):.3f}s min={min(samples):.3f}s max={max(samples):.3f}s")
    platform.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
