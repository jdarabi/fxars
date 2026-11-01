"""موتور تصمیم و سناریو."""

from fxars.decision.aggregation import aggregate_evidence, filter_usable, family_scores
from fxars.decision.scenario import ScenarioBuilder, ScenarioBuildResult
from fxars.decision.state_machine import ALLOWED, ScenarioStateMachine, can_transition
from fxars.decision.trigger import TriggerEvaluator, TriggerOutcome

__all__ = [
    "aggregate_evidence",
    "filter_usable",
    "family_scores",
    "ScenarioBuilder",
    "ScenarioBuildResult",
    "ScenarioStateMachine",
    "ALLOWED",
    "can_transition",
    "TriggerEvaluator",
    "TriggerOutcome",
]
