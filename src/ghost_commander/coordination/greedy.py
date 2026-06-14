"""Greedy nearest-with-priority assignment.

Each available agent (processed in id order) grabs the open task that maximizes
``priority_weight / (distance + eps)``. Fast and local; it can make globally
poor choices when several agents stampede the same high-priority task, which is
exactly the failure mode the comparison view is meant to expose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Assignment, can_fill, fill_slot, priority_weight

if TYPE_CHECKING:
    from ghost_commander.domain import World

_EPS = 1e-6


class GreedyStrategy:
    name = "greedy"

    def assign(self, world: World) -> list[Assignment]:
        assignments: list[Assignment] = []
        tasks = world.assignable_tasks()
        # remaining slots per task (skill or None), so we don't over-fill in a tick
        needs = {t.id: world.needed_slots(t) for t in tasks}
        for agent in sorted(world.available_agents(), key=lambda a: a.id):
            best_task_id: int | None = None
            best_score = -1.0
            for task in tasks:
                if not needs[task.id] or not can_fill(needs[task.id], agent):
                    continue
                d = agent.distance_to(task.x, task.y)
                score = priority_weight(task.priority_at(world.tick)) / (d + _EPS)
                if score > best_score or (score == best_score and (
                    best_task_id is None or task.id < best_task_id
                )):
                    best_score = score
                    best_task_id = task.id
            if best_task_id is not None:
                fill_slot(needs[best_task_id], agent)
                assignments.append((agent.id, best_task_id))
        return assignments


__all__ = ["GreedyStrategy"]
