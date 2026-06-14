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

import math
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ghost_commander.domain import Agent, Task, World

# A proposed assignment: (agent_id, task_id).
Assignment = tuple[int, int]

_EPS = 1e-6
# Deadline-aware tuning (shared by the triage strategy and the engine re-planner).
_URGENCY_GAIN = 4.0
_LOST_CAUSE_FACTOR = 0.04


def can_handle(agent: Agent, task: Task) -> bool:
    """Whether ``agent`` is eligible to work ``task`` (specialization check).

    Every strategy must respect this so it never routes the wrong kind of agent
    to a task; the engine also guards against it defensively.
    """
    return agent.has_skill(task.required_skill)


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


def urgency_score(agent: Agent, task: Task, tick: int) -> float:
    """Deadline-aware desirability of ``task`` for ``agent`` at ``tick``.

    Reduces to ``priority_weight / distance`` when the task has no deadline. With
    a deadline it estimates whether the agent can still finish in time
    (``travel + work`` vs ``slack``): a lost cause is heavily deprioritized, a
    savable-but-tight task gets an urgency boost. Shared by the ``triage``
    strategy and the engine's continuous re-planner so both rank the same way.
    """
    distance = agent.distance_to(task.x, task.y)
    base = priority_weight(task.priority) / (distance + _EPS)
    if task.deadline_tick is None:
        return base
    travel = math.ceil(distance / max(agent.speed, _EPS))
    work = math.ceil(max(task.remaining, 0.0) / max(agent.capacity, _EPS))
    ttc = travel + work
    spare = (task.deadline_tick - tick) - ttc
    if spare < 0:
        return base * _LOST_CAUSE_FACTOR
    return base * (1.0 + _URGENCY_GAIN / (spare + 1.0))


__all__ = [
    "Assignment",
    "CoordinationStrategy",
    "can_handle",
    "priority_weight",
    "urgency_score",
]
