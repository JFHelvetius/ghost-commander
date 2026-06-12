"""Greedy nearest-with-priority assignment.

Each available agent (processed in id order) grabs the open task that maximizes
``priority_weight / (distance + eps)``. Fast and local; it can make globally
poor choices when several agents stampede the same high-priority task, which is
exactly the failure mode the comparison view is meant to expose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Assignment, priority_weight

if TYPE_CHECKING:
    from ghost_commander.domain import World

_EPS = 1e-6


class GreedyStrategy:
    name = "greedy"

    def assign(self, world: World) -> list[Assignment]:
        assignments: list[Assignment] = []
        # Local view of remaining capacity per task so we don't over-fill within a tick.
        slots = {t.id: t.required_agents - len(t.assigned) for t in world.assignable_tasks()}
        for agent in sorted(world.available_agents(), key=lambda a: a.id):
            best_task_id: int | None = None
            best_score = -1.0
            for task in world.assignable_tasks():
                if slots.get(task.id, 0) <= 0:
                    continue
                d = agent.distance_to(task.x, task.y)
                score = priority_weight(task.priority) / (d + _EPS)
                # id tie-break keeps determinism
                if score > best_score or (score == best_score and (
                    best_task_id is None or task.id < best_task_id
                )):
                    best_score = score
                    best_task_id = task.id
            if best_task_id is not None:
                slots[best_task_id] -= 1
                assignments.append((agent.id, best_task_id))
        return assignments


__all__ = ["GreedyStrategy"]
