"""In-process metrics registry (Prometheus text exposition format)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


@dataclass
class _Histogram:
    buckets: tuple = LATENCY_BUCKETS
    counts: dict = field(default_factory=lambda: defaultdict(int))
    sum: float = 0.0
    total: int = 0

    def observe(self, value: float) -> None:
        self.sum += value
        self.total += 1
        for bucket in self.buckets:
            if value <= bucket:
                self.counts[bucket] += 1
                break
        else:
            self.counts[float("inf")] += 1


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._counters = defaultdict(float)
        self._gauges = {}
        self._histograms = {}
        self._start_time = time.monotonic()

    @staticmethod
    def _key(name, labels):
        if not labels:
            return name, ()
        return name, tuple(sorted(labels.items()))

    def inc_counter(self, name, *, labels=None, value=1.0):
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value

    def set_gauge(self, name, value, *, labels=None):
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = float(value)

    def observe_latency(self, name, seconds, *, labels=None):
        key = self._key(name, labels)
        with self._lock:
            hist = self._histograms.get(key)
            if hist is None:
                hist = _Histogram()
                self._histograms[key] = hist
            hist.observe(seconds)

    def snapshot(self):
        with self._lock:
            return {
                "uptime_seconds": round(time.monotonic() - self._start_time, 3),
                "counters": [{"name": n, "labels": dict(lbl), "value": round(v, 6)} for (n, lbl), v in self._counters.items()],
                "gauges": [{"name": n, "labels": dict(lbl), "value": round(v, 6)} for (n, lbl), v in self._gauges.items()],
                "histograms": [{"name": n, "labels": dict(lbl), "count": h.total, "sum": round(h.sum, 6)} for (n, lbl), h in self._histograms.items()],
            }

    def render_prometheus(self):
        lines = []
        with self._lock:
            for (name, labels), value in self._counters.items():
                lines.append(self._format(name, labels, value))
            for (name, labels), value in self._gauges.items():
                lines.append(self._format(name, labels, value))
            for (name, labels), hist in self._histograms.items():
                cumulative = 0
                for bucket in sorted([*hist.buckets, float("inf")]):
                    cumulative += hist.counts.get(bucket, 0)
                    ld = dict(labels) if labels else {}
                    ld["le"] = str(bucket)
                    lines.append(name + "_bucket" + self._labels(ld) + " " + str(cumulative))
                lines.append(self._format(name + "_sum", labels, hist.sum))
                lines.append(self._format(name + "_count", labels, hist.total))
        return chr(10).join(lines) + chr(10)

    @staticmethod
    def _labels(labels):
        if not labels:
            return ""
        pairs = []
        for k in sorted(labels.keys()):
            pairs.append(k + chr(61) + chr(34) + str(labels[k]) + chr(34))
        return chr(123) + ",".join(pairs) + chr(125)

    def _format(self, name, labels, value):
        return name + self._labels(dict(labels)) + " " + str(value)


_REGISTRY = MetricsRegistry()


def get_registry():
    return _REGISTRY
