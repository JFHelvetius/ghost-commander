"""Real-time metrics derived from world state each tick."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from ghost_commander.domain import TaskStatus

if TYPE_CHECKING:
    from ghost_commander.domain import World


@dataclass(frozen=True)
class MetricsSnapshot:
    tick: int
    agents_alive: int
    agents_total: int
    tasks_done: int
    tasks_total: int
    tasks_in_progress: int
    tasks_pending: int
    # weighted by priority — the number the commander actually cares about
    priority_completed: int
    priority_total: int
    mission_completion: float  # priority-weighted fraction in [0, 1]
    reassignments: int
    mean_resources: float

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def compute_metrics(world: World, tick: int, reassignments: int) -> MetricsSnapshot:
    tasks = list(world.tasks.values())
    agents = list(world.agents.values())

    done = [t for t in tasks if t.status is TaskStatus.DONE]
    in_prog = sum(1 for t in tasks if t.status is TaskStatus.IN_PROGRESS)
    pending = sum(1 for t in tasks if t.status is TaskStatus.PENDING)

    priority_total = sum(int(t.priority) for t in tasks) or 1
    priority_completed = sum(int(t.priority) for t in done)

    alive = [a for a in agents if a.alive]
    mean_res = sum(a.resources for a in alive) / len(alive) if alive else 0.0

    return MetricsSnapshot(
        tick=tick,
        agents_alive=len(alive),
        agents_total=len(agents),
        tasks_done=len(done),
        tasks_total=len(tasks),
        tasks_in_progress=in_prog,
        tasks_pending=pending,
        priority_completed=priority_completed,
        priority_total=priority_total,
        mission_completion=priority_completed / priority_total,
        reassignments=reassignments,
        mean_resources=mean_res,
    )


__all__ = ["MetricsSnapshot", "compute_metrics"]
