"""Coordination strategies — the interchangeable brains of the commander."""

from __future__ import annotations

from .auction import AuctionStrategy
from .base import Assignment, CoordinationStrategy, priority_weight, urgency_score
from .global_opt import GlobalStrategy
from .greedy import GreedyStrategy
from .optimal import OptimalStrategy
from .triage import TriageStrategy

#: Registry used by the CLI, dashboard and comparison tooling.
STRATEGIES: dict[str, type] = {
    GreedyStrategy.name: GreedyStrategy,
    AuctionStrategy.name: AuctionStrategy,
    GlobalStrategy.name: GlobalStrategy,
    TriageStrategy.name: TriageStrategy,
    OptimalStrategy.name: OptimalStrategy,
}


def make_strategy(name: str) -> CoordinationStrategy:
    try:
        return STRATEGIES[name]()  # type: ignore[return-value]
    except KeyError:
        raise ValueError(
            f"unknown strategy {name!r}; choices: {', '.join(sorted(STRATEGIES))}"
        ) from None


__all__ = [
    "STRATEGIES",
    "Assignment",
    "AuctionStrategy",
    "CoordinationStrategy",
    "GlobalStrategy",
    "GreedyStrategy",
    "OptimalStrategy",
    "TriageStrategy",
    "make_strategy",
    "priority_weight",
    "urgency_score",
]
