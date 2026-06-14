"""World: the 2D arena holding all agents and tasks plus spatial bookkeeping."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .agent import Agent, AgentStatus
from .task import Task, TaskStatus


@dataclass
class World:
    """Mutable container for the simulation state at a point in time."""

    width: float
    height: float
    agents: dict[int, Agent] = field(default_factory=dict)
    tasks: dict[int, Task] = field(default_factory=dict)
    # recharge depots; agents low on resources refuel here. Empty = no recovery.
    bases: list[tuple[float, float]] = field(default_factory=list)
    # current simulation tick — part of the state, so deadline-aware strategies
    # can reason about urgency without changing the pure assign(world) interface.
    tick: int = 0

    def nearest_base(self, x: float, y: float) -> tuple[float, float] | None:
        if not self.bases:
            return None
        return min(self.bases, key=lambda b: math.hypot(b[0] - x, b[1] - y))

    # ------------------------------------------------------------------ adds
    def add_agent(self, agent: Agent) -> None:
        self.agents[agent.id] = agent

    def add_task(self, task: Task) -> None:
        self.tasks[task.id] = task

    # ----------------------------------------------------------------- views
    def alive_agents(self) -> list[Agent]:
        return [a for a in self.agents.values() if a.alive]

    def available_agents(self) -> list[Agent]:
        return [a for a in self.agents.values() if a.available]

    def open_tasks(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.open]

    def assignable_tasks(self) -> list[Task]:
        """Open tasks that still have an unfilled slot."""
        return [t for t in self.tasks.values() if self.needed_slots(t)]

    def needed_slots(self, task: Task) -> list[str | None]:
        """The slots this task still needs, one per entry, as a skill or ``None``.

        Unifies the three cases: a plain task -> ``[None] * free`` (any agent); a
        single-skill task -> ``[skill] * free``; a mixed task (``required_skills``)
        -> the list of required skills not yet covered by an assigned agent.
        """
        if not task.open:
            return []
        if task.required_skills:
            covered = {
                self.agents[a].skill
                for a in task.assigned
                if a in self.agents and self.agents[a].alive
            }
            return [s for s in task.required_skills if s not in covered]
        free = task.required_agents - len(task.assigned)
        return [task.required_skill] * max(0, free)

    def task_of(self, agent: Agent) -> Task | None:
        return self.tasks.get(agent.task_id) if agent.task_id is not None else None

    # ------------------------------------------------------------- mutations
    def unassign_agent(self, agent: Agent) -> None:
        """Detach an agent from its task and roll the task back to PENDING if empty."""
        task = self.task_of(agent)
        agent.task_id = None
        if agent.alive:
            agent.status = AgentStatus.IDLE
        if task is None:
            return
        task.assigned.discard(agent.id)
        if not task.assigned and task.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS):
            task.status = TaskStatus.PENDING

    # -------------------------------------------------------------- counters
    @property
    def tasks_done(self) -> int:
        return sum(1 for t in self.tasks.values() if t.status is TaskStatus.DONE)

    @property
    def tasks_total(self) -> int:
        return len(self.tasks)

    @property
    def agents_alive(self) -> int:
        return sum(1 for a in self.agents.values() if a.alive)

    def snapshot(self) -> dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            "agents": [a.snapshot() for a in self.agents.values()],
            "tasks": [t.snapshot() for t in self.tasks.values()],
            "bases": [[round(x, 3), round(y, 3)] for x, y in self.bases],
        }


__all__ = ["World"]
