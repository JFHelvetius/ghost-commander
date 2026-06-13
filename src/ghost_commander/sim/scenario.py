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

    # deadlines: a task must be DONE by created_tick + ceil(workload * slack_factor)
    # + slack_base. Off by default (deadline_slack_factor <= 0) so the hero demo
    # still completes; turn on for "contested" missions where success can be lost.
    deadline_slack_factor: float = 0.0
    deadline_slack_base: int = 0

    # dynamic task arrival: tasks that appear *during* the mission (a changing
    # environment). ``dynamic_tasks`` extra tasks arrive at spawn ticks drawn
    # uniformly in [arrival_start_tick, arrival_end_tick]. 0 = static world.
    dynamic_tasks: int = 0
    arrival_start_tick: int = 5
    arrival_end_tick: int = 80

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
            world.add_task(self._make_task(j, rng, created_tick=0))
        return world

    def schedule_arrivals(self, root: RandomSource) -> list[Task]:
        """Tasks that arrive during the mission, sorted by spawn tick.

        Drawn from a dedicated ``arrivals`` stream so turning arrivals on does
        not perturb the initial layout or the failure sequence. With
        ``dynamic_tasks == 0`` this draws nothing -> existing scenarios keep
        their exact digests.
        """
        if self.dynamic_tasks <= 0:
            return []
        rng = root.child("arrivals")
        arrivals: list[Task] = []
        for k in range(self.dynamic_tasks):
            spawn = rng.integers(self.arrival_start_tick, self.arrival_end_tick + 1)
            arrivals.append(self._make_task(self.n_tasks + k, rng, created_tick=spawn))
        arrivals.sort(key=lambda t: (t.created_tick, t.id))
        return arrivals

    def _make_task(self, task_id: int, rng: RandomSource, created_tick: int) -> Task:
        # Preserve draw order x, y, priority, workload so the scenario
        # realization stays stable as fields are added.
        x = rng.uniform(0, self.width)
        y = rng.uniform(0, self.height)
        priority = self._draw_priority(rng)
        workload = rng.uniform(self.task_min_workload, self.task_max_workload)
        offset = self._deadline_offset(workload)
        return Task(
            id=task_id,
            x=x,
            y=y,
            priority=priority,
            workload=workload,
            required_agents=1,
            created_tick=created_tick,
            deadline_tick=None if offset is None else created_tick + offset,
        )

    def _deadline_offset(self, workload: float) -> int | None:
        if self.deadline_slack_factor <= 0:
            return None
        import math

        return self.deadline_slack_base + math.ceil(workload * self.deadline_slack_factor)

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
    # Contested: deadlines ON + a leaner fleet under sustained attrition, so the
    # mission can genuinely be *lost*. This is where coordination quality shows
    # up as success, not just speed — good strategies save more high-priority
    # tasks before they expire.
    "contested": Scenario(
        name="contested",
        seed=11,
        n_agents=55,
        n_tasks=60,
        max_ticks=260,
        agent_speed=2.6,
        random_failure_rate=0.006,
        shock_tick=20,
        shock_failure_rate=0.35,
        deadline_slack_factor=4.0,
        deadline_slack_base=16,
    ),
    # Rush: deadlines so tight that most tasks are at risk, but the mission is
    # winnable *if you triage*. This is where deadline-awareness pays off — the
    # `triage` strategy drops lost causes and rushes savable at-risk tasks,
    # beating the time-blind strategies on mission success.
    "rush": Scenario(
        name="rush",
        seed=42,
        n_agents=50,
        n_tasks=60,
        max_ticks=240,
        agent_speed=2.6,
        random_failure_rate=0.004,
        shock_tick=18,
        shock_failure_rate=0.30,
        deadline_slack_factor=2.5,
        deadline_slack_base=8,
    ),
    # Streaming: a *changing environment*. Only a third of the work exists at
    # t=0; the rest arrives in waves during the mission, each new task with its
    # own deadline. The commander can never plan once — it must keep
    # reorganizing as the objective set shifts under it.
    "streaming": Scenario(
        name="streaming",
        seed=42,
        n_agents=60,
        n_tasks=20,
        dynamic_tasks=60,
        arrival_start_tick=5,
        arrival_end_tick=120,
        max_ticks=320,
        agent_speed=2.8,
        random_failure_rate=0.003,
        shock_tick=40,
        shock_failure_rate=0.30,
        deadline_slack_factor=3.0,
        deadline_slack_base=12,
    ),
}


__all__ = ["PRESETS", "Scenario"]
