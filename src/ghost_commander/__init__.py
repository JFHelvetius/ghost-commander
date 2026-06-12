"""Ghost Commander — coordinate hundreds of autonomous agents in changing
environments, maximizing mission success through dynamic resource reassignment.

A standalone project that *reuses concepts* from Project Ghost (deterministic
clock, hierarchical RNG, typed event bus) without depending on it.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .sim import Scenario, Simulation, compare_strategies, run_scenario

__all__ = [
    "Scenario",
    "Simulation",
    "__version__",
    "compare_strategies",
    "run_scenario",
]
