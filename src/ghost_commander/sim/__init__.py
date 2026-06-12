"""Simulation engine, failure model, metrics, recording and comparison."""

from .comparison import StrategyResult, compare_strategies
from .engine import Simulation, run_scenario
from .failures import FailureModel, FailureOutcome
from .metrics import MetricsSnapshot, compute_metrics
from .recorder import RunRecording
from .scenario import PRESETS, Scenario

__all__ = [
    "PRESETS",
    "FailureModel",
    "FailureOutcome",
    "MetricsSnapshot",
    "RunRecording",
    "Scenario",
    "Simulation",
    "StrategyResult",
    "compare_strategies",
    "compute_metrics",
    "run_scenario",
]
