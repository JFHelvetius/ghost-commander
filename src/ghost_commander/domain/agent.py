"""Autonomous agent: the resource the commander assigns and reorganizes."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum


class AgentStatus(StrEnum):
    IDLE = "idle"  # alive, no task
    MOVING = "moving"  # en route to assigned task
    WORKING = "working"  # at task location, doing work
    FAILED = "failed"  # lost (resource depletion or random failure)


@dataclass
class Agent:
    """A single autonomous unit on the 2D map.

    ``resources`` is a 0..1 budget (think battery / fuel / supplies). It drains
    while working and on random failure events; at 0 the agent is lost. ``speed``
    is map-units per tick. ``capacity`` is how much workload it clears per tick
    while working.
    """

    id: int
    x: float
    y: float
    speed: float = 4.0
    capacity: float = 1.0
    resources: float = 1.0
    status: AgentStatus = AgentStatus.IDLE
    task_id: int | None = None
    # bookkeeping
    distance_travelled: float = 0.0
    work_done: float = 0.0
    failed_tick: int | None = field(default=None)

    @property
    def alive(self) -> bool:
        return self.status is not AgentStatus.FAILED

    @property
    def available(self) -> bool:
        """Alive and free to take a new assignment."""
        return self.alive and self.task_id is None

    def distance_to(self, x: float, y: float) -> float:
        return math.hypot(self.x - x, self.y - y)

    def move_toward(self, x: float, y: float) -> bool:
        """Move up to ``speed`` units toward ``(x, y)``. Returns True if arrived."""
        d = self.distance_to(x, y)
        if d <= self.speed:
            self.distance_travelled += d
            self.x, self.y = x, y
            return True
        ux, uy = (x - self.x) / d, (y - self.y) / d
        self.x += ux * self.speed
        self.y += uy * self.speed
        self.distance_travelled += self.speed
        return False

    def snapshot(self) -> dict[str, float | int | str | None]:
        return {
            "id": self.id,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "resources": round(self.resources, 4),
            "status": str(self.status),
            "task_id": self.task_id,
        }


__all__ = ["Agent", "AgentStatus"]
