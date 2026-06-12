"""Coordination strategy interface.

A strategy is a *pure* function of the current world: given who is available and
which tasks still need agents, it proposes new ``(agent_id, task_id)`` pairings.
It must be deterministic — no clocks, no global RNG, ties broken by id — so that
replay and the strategy comparison are reproducible (a Ghost discipline:
*same input -> same output, bit for bit*).

The engine owns all mutation (movement, work, failures, reassignment timing).
Strategies only decide *who goes where*.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ghost_commander.domain import World

# A proposed assignment: (agent_id, task_id).
Assignment = tuple[int, int]


@runtime_checkable
class CoordinationStrategy(Protocol):
    name: str

    def assign(self, world: World) -> list[Assignment]:
        """Return new agent->task pairings for currently-available agents."""
        ...


def priority_weight(priority: int) -> float:
    """Convex emphasis on priority so VITAL tasks dominate distance.

    Squaring keeps the ordering intuitive while making a priority-5 task worth
    far more than a priority-1 task at equal distance.
    """
    return float(priority) ** 2


__all__ = ["Assignment", "CoordinationStrategy", "priority_weight"]
