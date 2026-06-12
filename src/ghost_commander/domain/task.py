"""Task: a unit of mission work the commander must get completed."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum


class TaskPriority(IntEnum):
    """Higher value = more important. Drives weighting in every strategy."""

    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4
    VITAL = 5


class TaskStatus(StrEnum):
    PENDING = "pending"  # not yet assigned
    ASSIGNED = "assigned"  # an agent is en route
    IN_PROGRESS = "in_progress"  # being worked on
    DONE = "done"
    FAILED = "failed"  # abandoned and unrecoverable (MVP: not used unless deadline)


@dataclass
class Task:
    """A location on the map that needs ``workload`` units of work cleared.

    ``required_agents`` lets a task demand cooperation (e.g. 2 units). The MVP
    keeps it at 1 by default; the assignment strategies already account for it.
    """

    id: int
    x: float
    y: float
    priority: TaskPriority = TaskPriority.NORMAL
    workload: float = 10.0
    required_agents: int = 1
    status: TaskStatus = TaskStatus.PENDING
    assigned: set[int] = field(default_factory=set)
    # bookkeeping
    remaining: float = field(default=0.0)
    created_tick: int = 0
    done_tick: int | None = None

    def __post_init__(self) -> None:
        if self.remaining == 0.0:
            self.remaining = self.workload

    @property
    def progress(self) -> float:
        if self.workload <= 0:
            return 1.0
        return 1.0 - max(self.remaining, 0.0) / self.workload

    @property
    def open(self) -> bool:
        return self.status in (TaskStatus.PENDING, TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS)

    @property
    def needs_more_agents(self) -> bool:
        return self.open and len(self.assigned) < self.required_agents

    def snapshot(self) -> dict[str, object]:
        return {
            "id": self.id,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "priority": int(self.priority),
            "status": str(self.status),
            "progress": round(self.progress, 4),
            "assigned": sorted(self.assigned),
        }


__all__ = ["Task", "TaskPriority", "TaskStatus"]
