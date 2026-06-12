"""Coordination strategies — the interchangeable brains of the commander."""

from __future__ import annotations

from .auction import AuctionStrategy
from .base import Assignment, CoordinationStrategy, priority_weight
from .global_opt import GlobalStrategy
from .greedy import GreedyStrategy

#: Registry used by the CLI, dashboard and comparison tooling.
STRATEGIES: dict[str, type] = {
    GreedyStrategy.name: GreedyStrategy,
    AuctionStrategy.name: AuctionStrategy,
    GlobalStrategy.name: GlobalStrategy,
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
    "make_strategy",
    "priority_weight",
]
