"""Deadline-aware triage assignment.

The other strategies weigh priority against distance but ignore *time*. Under
deadlines that is a real blind spot: they will keep feeding agents to a juicy
high-priority task that can no longer be finished in time, while a savable task
quietly expires. Triage fixes that with an explicit estimate of whether a given
agent can still finish a given task before its deadline:

    ttc   = ceil(distance / speed) + ceil(remaining / capacity)   # ticks to complete
    slack = deadline_tick - world.tick                            # ticks available

- If ``slack < ttc`` the task is a *lost cause* for this agent -> heavily
  deprioritized (don't throw a good agent after a task that will fail anyway).
- If it is savable but tight (small ``slack - ttc``) -> urgency boost, scaled by
  priority, so the commander rushes the at-risk critical tasks first.

With deadlines off (no ``deadline_tick``) the score reduces to the same
priority/distance used by ``global``, so triage is a safe general default too.
Deterministic: ties broken by (-score, agent_id, task_id).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .base import Assignment, priority_weight

if TYPE_CHECKING:
    from ghost_commander.domain import Agent, Task, World

_EPS = 1e-6
# How hard to chase a savable-but-tight task. Higher = more aggressive triage.
_URGENCY_GAIN = 4.0
# What remains of a task's appeal once it looks unsavable by this agent.
_LOST_CAUSE_FACTOR = 0.04


class TriageStrategy:
    name = "triage"

    def assign(self, world: World) -> list[Assignment]:
        agents = sorted(world.available_agents(), key=lambda a: a.id)
        tasks = world.assignable_tasks()
        if not agents or not tasks:
            return []

        slots = {t.id: t.required_agents - len(t.assigned) for t in tasks}
        table: list[tuple[float, int, int]] = []  # (score, agent_id, task_id)
        for agent in agents:
            for task in tasks:
                table.append((self._score(agent, task, world.tick), agent.id, task.id))

        table.sort(key=lambda c: (-c[0], c[1], c[2]))

        assignments: list[Assignment] = []
        used: set[int] = set()
        for _score, agent_id, task_id in table:
            if agent_id in used or slots.get(task_id, 0) <= 0:
                continue
            assignments.append((agent_id, task_id))
            used.add(agent_id)
            slots[task_id] -= 1
            if len(used) == len(agents):
                break
        return assignments

    @staticmethod
    def _score(agent: Agent, task: Task, tick: int) -> float:
        distance = agent.distance_to(task.x, task.y)
        base = priority_weight(task.priority) / (distance + _EPS)

        if task.deadline_tick is None:
            return base

        travel = math.ceil(distance / max(agent.speed, _EPS))
        work = math.ceil(max(task.remaining, 0.0) / max(agent.capacity, _EPS))
        ttc = travel + work
        slack = task.deadline_tick - tick
        spare = slack - ttc

        if spare < 0:
            # lost cause for this agent: keep a faint pull so a free agent will
            # still attempt it if literally nothing else is available.
            return base * _LOST_CAUSE_FACTOR

        # savable: the tighter the window, the bigger the boost.
        return base * (1.0 + _URGENCY_GAIN / (spare + 1.0))


__all__ = ["TriageStrategy"]
