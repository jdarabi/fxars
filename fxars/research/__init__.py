"""پژوهش، بک‌تست و اعتبارسنجی."""

from fxars.research.backtest import BacktestConfig, BacktestEngine, BacktestOutput, EvidenceTimeline
from fxars.research.metrics import compute_metrics
from fxars.research.service import BacktestResult, ResearchService
from fxars.research.walkforward import WalkForwardResult, WalkForwardRunner

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestOutput",
    "EvidenceTimeline",
    "compute_metrics",
    "ResearchService",
    "BacktestResult",
    "WalkForwardRunner",
    "WalkForwardResult",
]
