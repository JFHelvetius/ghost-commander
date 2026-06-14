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

from typing import TYPE_CHECKING

from .base import Assignment, can_fill, fill_slot, urgency_score

if TYPE_CHECKING:
    from ghost_commander.domain import World


class TriageStrategy:
    name = "triage"

    def assign(self, world: World) -> list[Assignment]:
        agents = sorted(world.available_agents(), key=lambda a: a.id)
        tasks = world.assignable_tasks()
        if not agents or not tasks:
            return []

        needs = {t.id: world.needed_slots(t) for t in tasks}
        amap = {a.id: a for a in agents}
        table: list[tuple[float, int, int]] = []  # (score, agent_id, task_id)
        for agent in agents:
            for task in tasks:
                if not can_fill(needs[task.id], agent):
                    continue
                table.append((urgency_score(agent, task, world.tick), agent.id, task.id))

        table.sort(key=lambda c: (-c[0], c[1], c[2]))

        assignments: list[Assignment] = []
        used: set[int] = set()
        for _score, agent_id, task_id in table:
            if agent_id in used or not needs[task_id]:
                continue
            if not fill_slot(needs[task_id], amap[agent_id]):
                continue
            assignments.append((agent_id, task_id))
            used.add(agent_id)
            if len(used) == len(agents):
                break
        return assignments


__all__ = ["TriageStrategy"]
