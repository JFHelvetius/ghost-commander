"""Real-time metrics derived from world state each tick."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from ghost_commander.domain import AgentStatus, TaskStatus

if TYPE_CHECKING:
    from ghost_commander.domain import World


@dataclass(frozen=True)
class MetricsSnapshot:
    tick: int
    agents_alive: int
    agents_total: int
    agents_recharging: int
    recharges: int
    tasks_done: int
    tasks_total: int
    tasks_failed: int
    tasks_in_progress: int
    tasks_pending: int
    # weighted by priority — the number the commander actually cares about
    priority_completed: int
    priority_failed: int
    priority_total: int
    mission_completion: float  # priority-weighted fraction DONE, in [0, 1]
    coverage: float  # for recurring points: fraction "fresh" now (1.0 if none)
    reassignments: int
    mean_resources: float

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def compute_metrics(
    world: World, tick: int, reassignments: int, recharges: int = 0
) -> MetricsSnapshot:
    tasks = list(world.tasks.values())
    agents = list(world.agents.values())

    done = [t for t in tasks if t.status is TaskStatus.DONE]
    failed = [t for t in tasks if t.status is TaskStatus.FAILED]
    in_prog = sum(1 for t in tasks if t.status is TaskStatus.IN_PROGRESS)
    pending = sum(1 for t in tasks if t.status is TaskStatus.PENDING)

    priority_total = sum(int(t.priority) for t in tasks) or 1
    priority_completed = sum(int(t.priority) for t in done)
    priority_failed = sum(int(t.priority) for t in failed)

    alive = [a for a in agents if a.alive]
    mean_res = sum(a.resources for a in alive) / len(alive) if alive else 0.0

    recurring = [t for t in tasks if t.revisit_every is not None]
    coverage = (
        sum(1 for t in recurring if t.is_fresh(tick)) / len(recurring)
        if recurring else 1.0
    )

    return MetricsSnapshot(
        tick=tick,
        agents_alive=len(alive),
        agents_total=len(agents),
        agents_recharging=sum(1 for a in alive if a.status is AgentStatus.RECHARGING),
        recharges=recharges,
        tasks_done=len(done),
        tasks_total=len(tasks),
        tasks_failed=len(failed),
        tasks_in_progress=in_prog,
        tasks_pending=pending,
        priority_completed=priority_completed,
        priority_failed=priority_failed,
        priority_total=priority_total,
        mission_completion=priority_completed / priority_total,
        coverage=coverage,
        reassignments=reassignments,
        mean_resources=mean_res,
    )


__all__ = ["MetricsSnapshot", "compute_metrics"]
