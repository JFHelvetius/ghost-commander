"""World: the 2D arena holding all agents and tasks plus spatial bookkeeping."""

from __future__ import annotations

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
        """Open tasks still short of their required agent count."""
        return [t for t in self.tasks.values() if t.needs_more_agents]

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
            "agents": [a.snapshot() for a in self.agents.values()],
            "tasks": [t.snapshot() for t in self.tasks.values()],
        }


__all__ = ["World"]
