"""Scenario specification + deterministic world construction.

A scenario is everything you need to reproduce a mission: fleet size, task field,
failure rates and the root seed. Building the world pulls all randomness from a
labelled child of the root ``RandomSource`` so two runs of the same scenario are
identical, and the failure stream (a different child) is independent of layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ghost_commander.core import RandomSource
from ghost_commander.domain import Agent, Task, TaskPriority, World


@dataclass(frozen=True)
class Scenario:
    name: str = "default"
    seed: int = 42
    width: float = 200.0
    height: float = 200.0
    n_agents: int = 100
    n_tasks: int = 55
    max_ticks: int = 400

    # agent params
    agent_speed: float = 3.0
    agent_capacity: float = 1.0

    # task params
    task_min_workload: float = 12.0
    task_max_workload: float = 30.0

    # failure model (per agent, per tick)
    resource_drain_working: float = 0.012  # baseline drain while working
    resource_drain_moving: float = 0.004
    random_failure_rate: float = 0.0006  # hard loss, independent of resources
    shock_tick: int | None = 18  # a coordinated shock wave (e.g. jamming) mid-mission ...
    shock_failure_rate: float = 0.35  # ... that fails ~35% of the fleet at once
    recovery_rate: float = 0.0  # MVP: failures are permanent

    # priority distribution weights for LOW..VITAL (1..5)
    priority_weights: tuple[float, ...] = (0.30, 0.30, 0.22, 0.13, 0.05)

    labels: dict[str, str] = field(default_factory=dict)

    def build_world(self, root: RandomSource) -> World:
        rng = root.child("layout")
        world = World(width=self.width, height=self.height)

        for i in range(self.n_agents):
            world.add_agent(
                Agent(
                    id=i,
                    x=rng.uniform(0, self.width),
                    y=rng.uniform(0, self.height),
                    speed=self.agent_speed,
                    capacity=self.agent_capacity,
                    resources=1.0,
                )
            )

        for j in range(self.n_tasks):
            world.add_task(
                Task(
                    id=j,
                    x=rng.uniform(0, self.width),
                    y=rng.uniform(0, self.height),
                    priority=self._draw_priority(rng),
                    workload=rng.uniform(self.task_min_workload, self.task_max_workload),
                    required_agents=1,
                )
            )
        return world

    def _draw_priority(self, rng: RandomSource) -> TaskPriority:
        r = rng.uniform(0, sum(self.priority_weights))
        acc = 0.0
        for idx, w in enumerate(self.priority_weights, start=1):
            acc += w
            if r <= acc:
                return TaskPriority(idx)
        return TaskPriority.VITAL


# A couple of presets so the demo is one keystroke.
PRESETS: dict[str, Scenario] = {
    "default": Scenario(),
    "swarm": Scenario(name="swarm", n_agents=200, n_tasks=80, max_ticks=600),
    "scarce": Scenario(
        name="scarce", n_agents=60, n_tasks=50, resource_drain_working=0.02, max_ticks=500
    ),
    "calm": Scenario(
        name="calm", random_failure_rate=0.0, shock_tick=None, resource_drain_working=0.008
    ),
}


__all__ = ["PRESETS", "Scenario"]
