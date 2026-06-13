"""Global cost-aware assignment.

Builds the full (available agent x open slot) score table and greedily commits
the best pairings overall, never letting one agent take two slots in a round.
This approximates a minimum-cost global matching: it weighs every agent against
every task simultaneously instead of locally (greedy) or per-task (auction),
which tends to spread the fleet more efficiently across the map. Deterministic
ordering by (-score, agent_id, task_id).

No SciPy dependency: a greedy global pass over the sorted score table is within
a few percent of optimal for this MVP and keeps the install lean.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Assignment, can_handle, priority_weight

if TYPE_CHECKING:
    from ghost_commander.domain import World

_EPS = 1e-6


class GlobalStrategy:
    name = "global"

    def assign(self, world: World) -> list[Assignment]:
        agents = sorted(world.available_agents(), key=lambda a: a.id)
        tasks = world.assignable_tasks()
        if not agents or not tasks:
            return []

        slots = {t.id: t.required_agents - len(t.assigned) for t in tasks}

        # Full score table across every agent/task pair.
        table: list[tuple[float, int, int]] = []  # (score, agent_id, task_id)
        for agent in agents:
            for task in tasks:
                if not can_handle(agent, task):
                    continue
                d = agent.distance_to(task.x, task.y)
                score = priority_weight(task.priority) / (d + _EPS)
                table.append((score, agent.id, task.id))

        table.sort(key=lambda c: (-c[0], c[1], c[2]))

        assignments: list[Assignment] = []
        used_agents: set[int] = set()
        for _score, agent_id, task_id in table:
            if agent_id in used_agents or slots.get(task_id, 0) <= 0:
                continue
            assignments.append((agent_id, task_id))
            used_agents.add(agent_id)
            slots[task_id] -= 1
            if len(used_agents) == len(agents):
                break
        return assignments


__all__ = ["GlobalStrategy"]
