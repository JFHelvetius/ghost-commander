"""Optimal per-tick assignment (exact, via the Hungarian algorithm).

`greedy`, `auction` and `global` are heuristics that approximate, more or less
well, the assignment that maximizes total ``priority_weight / distance``.
``optimal`` solves that *exactly* each tick (max-weight bipartite matching), so
it is the rigorous upper bound for that per-tick objective — you can read off how
far each heuristic falls short.

Note it is only *per-tick* optimal (myopic): it does not look ahead in time, so a
deadline-aware strategy like ``triage`` can still beat it on mission outcome under
tight deadlines. That gap is itself an honest, instructive result.

Falls back to the greedy-global pass on very large instances to stay responsive
(Hungarian is O(n^3) in pure Python).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import _hungarian
from .base import Assignment, can_handle, priority_weight
from .global_opt import GlobalStrategy

if TYPE_CHECKING:
    from ghost_commander.domain import World

_EPS = 1e-6
_MAX_N = 140  # above this, fall back to greedy-global for the tick (keeps it fast)
_INELIGIBLE = -1e12  # profit for a forbidden (wrong-skill) pairing


class OptimalStrategy:
    name = "optimal"

    def __init__(self) -> None:
        self._fallback = GlobalStrategy()

    def assign(self, world: World) -> list[Assignment]:
        agents = sorted(world.available_agents(), key=lambda a: a.id)
        tasks = world.assignable_tasks()
        if not agents or not tasks:
            return []

        # expand each task into one column per free slot
        slots: list[int] = []  # task id per column
        for task in sorted(tasks, key=lambda t: t.id):
            slots.extend([task.id] * (task.required_agents - len(task.assigned)))
        if not slots:
            return []

        n = max(len(agents), len(slots))
        if n > _MAX_N:
            return self._fallback.assign(world)

        tmap = {t.id: t for t in tasks}
        # profit[i][j]: value of agent i on slot j (0 for dummy rows/cols)
        profit = [[0.0] * n for _ in range(n)]
        max_p = _EPS
        for i, agent in enumerate(agents):
            for j, tid in enumerate(slots):
                task = tmap[tid]
                if not can_handle(agent, task):
                    profit[i][j] = _INELIGIBLE
                    continue
                p = priority_weight(task.priority) / (agent.distance_to(task.x, task.y) + _EPS)
                profit[i][j] = p
                if p > max_p:
                    max_p = p

        # min-cost = (max_profit - profit); dummies cost max_p, ineligible huge
        cost = [[max_p - profit[i][j] for j in range(n)] for i in range(n)]
        row_to_col = _hungarian.solve(cost)

        assignments: list[Assignment] = []
        for i, agent in enumerate(agents):
            j = row_to_col[i]
            if j < len(slots) and profit[i][j] > 0.0:  # real, eligible, beneficial
                assignments.append((agent.id, slots[j]))
        return assignments


__all__ = ["OptimalStrategy"]
