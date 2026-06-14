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

    # recovery: agents at or below recharge_threshold are pulled off duty and
    # routed to the nearest base, regaining recharge_rate per tick until they
    # reach recharge_target, then return to the pool. n_bases == 0 disables it
    # (no extra RNG draws -> existing scenario digests unchanged).
    n_bases: int = 0
    recharge_threshold: float = 0.25
    recharge_rate: float = 0.15
    recharge_target: float = 1.0

    # failure model (per agent, per tick)
    resource_drain_working: float = 0.012  # baseline drain while working
    resource_drain_moving: float = 0.004
    random_failure_rate: float = 0.0006  # hard loss, independent of resources
    shock_tick: int | None = 18  # a coordinated shock wave (e.g. jamming) mid-mission ...
    shock_failure_rate: float = 0.35  # ... that fails ~35% of the fleet at once
    recovery_rate: float = 0.0  # MVP: failures are permanent

    # priority distribution weights for LOW..VITAL (1..5)
    priority_weights: tuple[float, ...] = (0.30, 0.30, 0.22, 0.13, 0.05)

    # specialization (opt-in). ``agent_skills`` is the roster of skills; each
    # agent gets exactly one, drawn with ``agent_skill_weights`` (uneven weights
    # make a skill scarce -> a bottleneck the commander must manage). Each task
    # requires one of those skills (also weighted). Empty roster = homogeneous
    # fleet, no extra RNG draws, existing scenario digests unchanged.
    agent_skills: tuple[str, ...] = ()
    agent_skill_weights: tuple[float, ...] = ()
    task_skill_weights: tuple[float, ...] = ()

    # cooperative tasks (opt-in): a fraction of tasks need a *team* of
    # ``cooperative_agents`` present simultaneously to make progress. 0 = none
    # (no extra RNG draw -> existing scenario digests unchanged).
    cooperative_fraction: float = 0.0
    cooperative_agents: int = 2

    # mixed-specialist tasks (opt-in): a fraction of tasks need one agent of EACH
    # of ``mixed_skill_count`` distinct skills present at once. Requires
    # ``agent_skills``. 0 = none (no extra RNG draw -> digests unchanged).
    mixed_skill_fraction: float = 0.0
    mixed_skill_count: int = 2

    # dynamic priority (opt-in): every N ticks a lingering task's effective
    # priority rises by one. 0 = static (no change to scheduling).
    priority_escalation: int = 0

    # heterogeneous fleet (opt-in): each agent's speed/capacity is drawn within
    # ±spread of the base (fractional, e.g. 0.5 = ±50%). 0 = uniform fleet (no
    # extra RNG draw -> existing scenario digests unchanged).
    agent_speed_spread: float = 0.0
    agent_capacity_spread: float = 0.0

    # precedence (opt-in): each task (after the first) depends on an earlier one
    # with probability ``precedence_fraction`` — it stays locked until that
    # prerequisite is DONE. 0 = no dependencies (no extra RNG draw -> digests
    # unchanged). Only earlier ids are referenced, so the graph is acyclic.
    precedence_fraction: float = 0.0

    # recurring / persistent monitoring (opt-in): every task must be re-serviced
    # every ``revisit_every`` ticks. 0 = one-shot tasks. With this on, the
    # objective is maintaining *coverage*, not finishing.
    revisit_every: int = 0

    labels: dict[str, str] = field(default_factory=dict)

    def build_world(self, root: RandomSource) -> World:
        rng = root.child("layout")
        world = World(width=self.width, height=self.height)

        for i in range(self.n_agents):
            x = rng.uniform(0, self.width)
            y = rng.uniform(0, self.height)
            skills = self._draw_agent_skill(rng)
            speed = self._spread(rng, self.agent_speed, self.agent_speed_spread)
            capacity = self._spread(rng, self.agent_capacity, self.agent_capacity_spread)
            world.add_agent(
                Agent(
                    id=i,
                    x=x,
                    y=y,
                    speed=speed,
                    capacity=capacity,
                    resources=1.0,
                    skills=skills,
                )
            )

        for j in range(self.n_tasks):
            world.add_task(self._make_task(j, rng, created_tick=0))

        # Bases drawn last so adding them never perturbs agent/task layout; only
        # drawn when enabled, so n_bases == 0 keeps existing digests intact.
        for _ in range(self.n_bases):
            world.bases.append((rng.uniform(0, self.width), rng.uniform(0, self.height)))

        # Precedence assigned last and only when enabled, so it never perturbs
        # the layout of existing scenarios. Each task may depend on one earlier
        # task (acyclic by construction).
        if self.precedence_fraction > 0:
            ids = sorted(world.tasks)
            for j in ids[1:]:
                if rng.chance(self.precedence_fraction):
                    world.tasks[j].requires = (ids[rng.integers(0, ids.index(j))],)
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
        required_skill = self._draw_task_skill(rng)
        required_agents = self._draw_team_size(rng)
        required_skills = self._draw_mixed_skills(rng)
        if required_skills:
            required_skill = None  # a mixed task needs each listed skill, not one
            required_agents = 1    # __post_init__ resets it to len(required_skills)
        return Task(
            id=task_id,
            x=x,
            y=y,
            priority=priority,
            workload=workload,
            required_agents=required_agents,
            created_tick=created_tick,
            deadline_tick=None if offset is None else created_tick + offset,
            required_skill=required_skill,
            required_skills=required_skills,
            escalate_every=self.priority_escalation or None,
            revisit_every=self.revisit_every or None,
        )

    @staticmethod
    def _spread(rng: RandomSource, base: float, spread: float) -> float:
        """``base`` jittered within ±spread (fraction). spread<=0 -> no RNG draw."""
        if spread <= 0:
            return base
        return max(0.1, base * rng.uniform(1.0 - spread, 1.0 + spread))

    def _draw_team_size(self, rng: RandomSource) -> int:
        if self.cooperative_fraction <= 0:
            return 1
        return self.cooperative_agents if rng.chance(self.cooperative_fraction) else 1

    def _draw_mixed_skills(self, rng: RandomSource) -> tuple[str, ...]:
        if self.mixed_skill_fraction <= 0 or len(self.agent_skills) < self.mixed_skill_count:
            return ()
        if not rng.chance(self.mixed_skill_fraction):
            return ()
        pool = list(self.agent_skills)
        chosen: list[str] = []
        for _ in range(self.mixed_skill_count):
            chosen.append(pool.pop(rng.integers(0, len(pool))))
        return tuple(sorted(chosen))

    def _draw_agent_skill(self, rng: RandomSource) -> frozenset[str]:
        if not self.agent_skills:
            return frozenset()
        return frozenset({self._weighted_choice(rng, self.agent_skills, self.agent_skill_weights)})

    def _draw_task_skill(self, rng: RandomSource) -> str | None:
        if not self.agent_skills:
            return None
        return self._weighted_choice(rng, self.agent_skills, self.task_skill_weights)

    @staticmethod
    def _weighted_choice(rng: RandomSource, items: tuple[str, ...], weights: tuple[float, ...]) -> str:
        w = weights if len(weights) == len(items) else tuple(1.0 for _ in items)
        r = rng.uniform(0, sum(w))
        acc = 0.0
        for item, wi in zip(items, w, strict=True):
            acc += wi
            if r <= acc:
                return item
        return items[-1]

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
    # Specialist: a heterogeneous fleet. Three skills, but "repair" agents are
    # scarce (20% of the fleet) while repair tasks are common — a bottleneck.
    # Now it is not enough to send the nearest agent; the commander must route
    # the right *kind* of agent and triage the scarce specialists. Deadlines on.
    "specialist": Scenario(
        name="specialist",
        seed=42,
        n_agents=60,
        n_tasks=60,
        max_ticks=300,
        agent_speed=2.8,
        random_failure_rate=0.004,
        shock_tick=20,
        shock_failure_rate=0.30,
        deadline_slack_factor=3.5,
        deadline_slack_base=14,
        agent_skills=("recon", "repair", "medical"),
        agent_skill_weights=(0.5, 0.2, 0.3),   # repair is scarce
        task_skill_weights=(0.34, 0.33, 0.33),  # repair demand ~ even -> oversubscribed
    ),
    # Endurance: a long attritional mission with heavy resource drain. Without
    # bases the fleet burns out before clearing the field and the mission stalls
    # well under 100%; with recharge bases the commander keeps cycling agents
    # through refuel and sustains the fleet to finish. Recovery as a real lever.
    "endurance": Scenario(
        name="endurance",
        seed=42,
        n_agents=40,
        n_tasks=70,
        max_ticks=400,
        agent_speed=2.8,
        resource_drain_working=0.04,
        resource_drain_moving=0.015,
        random_failure_rate=0.004,
        shock_tick=None,
        n_bases=4,
        recharge_threshold=0.3,
        recharge_rate=0.2,
    ),
    # Joint: ~40% of tasks need a *team* of 2 on-site at once. Now the commander
    # must synchronize arrivals, not just route singletons — an agent that
    # arrives early waits (and drains), and a cooperative task stalls if one of
    # its team is lost. Coordination *between* agents, not just assignment.
    "joint": Scenario(
        name="joint",
        seed=42,
        n_agents=70,
        n_tasks=50,
        max_ticks=300,
        agent_speed=2.8,
        random_failure_rate=0.004,
        shock_tick=22,
        shock_failure_rate=0.30,
        deadline_slack_factor=4.0,
        deadline_slack_base=18,
        cooperative_fraction=0.4,
        cooperative_agents=2,
    ),
    # --- Military-flavoured COORDINATION / LOGISTICS cases (no targeting, no
    # weapons, no lethal decisions — this is a task-allocation simulator: which
    # unit goes to which point). They are ordinary combinations of the existing
    # mechanics with operational framing.
    #
    # ISR / reconnaissance: recon drones must observe points of interest before
    # their intel window closes (deadlines), under electronic-warfare jamming (a
    # shock that downs part of the fleet) and steady attrition.
    "recon": Scenario(
        name="recon",
        seed=42,
        n_agents=40,
        n_tasks=60,
        width=240.0,
        height=240.0,
        max_ticks=300,
        agent_speed=3.0,
        random_failure_rate=0.004,
        shock_tick=22,            # EW jamming event mid-mission
        shock_failure_rate=0.30,
        deadline_slack_factor=3.5,  # intel windows
        deadline_slack_base=16,
    ),
    # Contested logistics / resupply: autonomous transport delivers to forward
    # positions under heavy resource drain, sustained by recharge bases (FOBs).
    # Without good routing the fleet burns out before the field is served.
    "resupply": Scenario(
        name="resupply",
        seed=42,
        n_agents=45,
        n_tasks=65,
        width=240.0,
        height=240.0,
        max_ticks=460,
        agent_speed=2.8,
        resource_drain_working=0.038,
        resource_drain_moving=0.014,
        random_failure_rate=0.004,
        shock_tick=None,
        n_bases=4,
        recharge_threshold=0.3,
        recharge_rate=0.2,
        # no deadlines: this case is about *sustaining* the fleet through attrition
        # with FOB recharge, not punctuality (deadlines + recharge fight each other).
    ),
    # Search & rescue: reach survivors before their survival window closes (tight
    # deadlines); ~30% of cases need a 2-unit team to extract (cooperative tasks);
    # an aftershock thins the fleet. Triage's "save the savable" really pays here.
    "sar": Scenario(
        name="sar",
        seed=42,
        n_agents=40,
        n_tasks=50,
        width=220.0,
        height=220.0,
        max_ticks=280,
        agent_speed=3.0,
        random_failure_rate=0.003,
        shock_tick=18,            # aftershock
        shock_failure_rate=0.20,
        deadline_slack_factor=2.5,  # survival windows (tight)
        deadline_slack_base=10,
        cooperative_fraction=0.3,   # extractions need a 2-unit team
        cooperative_agents=2,
    ),
    # Persistent surveillance / area coverage: events to inspect appear across a
    # large area throughout the mission and must be handled promptly (deadlines)
    # with a modest fleet. The challenge is sustained coverage, not a one-off push.
    "patrol": Scenario(
        name="patrol",
        seed=42,
        n_agents=30,
        n_tasks=12,
        dynamic_tasks=70,
        arrival_start_tick=4,
        arrival_end_tick=240,     # a steady stream, not a wave
        width=280.0,
        height=280.0,
        max_ticks=340,
        agent_speed=3.0,
        random_failure_rate=0.002,
        shock_tick=None,
        deadline_slack_factor=2.5,  # events go stale if not inspected promptly
        deadline_slack_base=12,
    ),
    # Dynamic priorities: a task that waits gets more urgent (its effective
    # priority climbs every few ticks), so the commander must keep re-ranking a
    # lean fleet against a shock and tight deadlines.
    "escalating": Scenario(
        name="escalating",
        seed=42,
        n_agents=45,
        n_tasks=55,
        max_ticks=300,
        agent_speed=2.8,
        random_failure_rate=0.004,
        shock_tick=20,
        shock_failure_rate=0.30,
        deadline_slack_factor=3.0,
        deadline_slack_base=16,
        priority_escalation=12,   # +1 priority every 12 ticks a task lingers
    ),
    # Task force: ~40% of tasks need a *mix* of specialists at once (e.g. one
    # recon + one medical), on a heterogeneous fleet. The commander must send the
    # right combination to each task, not just enough bodies.
    "taskforce": Scenario(
        name="taskforce",
        seed=42,
        n_agents=60,
        n_tasks=55,
        max_ticks=300,
        agent_speed=2.8,
        random_failure_rate=0.004,
        shock_tick=22,
        shock_failure_rate=0.30,
        deadline_slack_factor=4.0,
        deadline_slack_base=18,
        agent_skills=("recon", "repair", "medical"),
        agent_skill_weights=(0.34, 0.33, 0.33),
        task_skill_weights=(0.34, 0.33, 0.33),
        mixed_skill_fraction=0.4,
        mixed_skill_count=2,
    ),
    # Mixed fleet: heterogeneous units — fast/slow, light/heavy — so *which* unit
    # fits a task depends on its capabilities, not just its position. Under
    # deadlines this rewards strategies that reason about each unit's real
    # time-to-complete (triage does; pure distance heuristics don't).
    "mixedfleet": Scenario(
        name="mixedfleet",
        seed=42,
        n_agents=45,
        n_tasks=55,
        max_ticks=300,
        agent_speed=3.0,
        agent_capacity=1.0,
        agent_speed_spread=0.6,      # speeds vary ±60% (scouts vs heavies)
        agent_capacity_spread=0.6,   # work rates vary ±60%
        task_min_workload=10.0,
        task_max_workload=34.0,      # wide workload range -> capability match matters
        random_failure_rate=0.004,
        shock_tick=20,
        shock_failure_rate=0.30,
        deadline_slack_factor=3.0,
        deadline_slack_base=14,
    ),
    # Phased operation: ~45% of tasks depend on an earlier one ("secure before
    # resupply") — they stay locked until their prerequisite is done, so the
    # mission unfolds in waves the commander unlocks by clearing the right tasks
    # first. Under attrition, dithering on the wrong tasks stalls whole branches.
    "phased": Scenario(
        name="phased",
        seed=42,
        n_agents=45,
        n_tasks=55,
        max_ticks=320,
        agent_speed=2.8,
        random_failure_rate=0.004,
        shock_tick=22,
        shock_failure_rate=0.30,
        precedence_fraction=0.45,
    ),
    # Persistent monitoring: every point must be re-serviced every ~40 ticks or it
    # goes stale. The objective is *maintaining coverage*, not finishing — the
    # commander must keep cycling a modest fleet over a wide field, forever.
    "monitor": Scenario(
        name="monitor",
        seed=42,
        n_agents=24,
        n_tasks=30,
        width=280.0,
        height=280.0,
        max_ticks=320,
        agent_speed=3.0,
        task_min_workload=4.0,
        task_max_workload=10.0,   # quick services, so revisit cadence dominates
        random_failure_rate=0.002,
        shock_tick=None,
        revisit_every=40,
    ),
}


__all__ = ["PRESETS", "Scenario"]
