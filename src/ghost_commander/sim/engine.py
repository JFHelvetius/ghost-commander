"""Simulation engine: the commander's clock-driven control loop.

Per tick the engine:

1. reassigns available agents to under-staffed tasks via the active strategy,
2. moves agents toward their task and lets them work it down,
3. applies the failure model (drain + random loss + shocks),
4. detaches lost agents so their tasks return to the pool (to be re-staffed next
   tick — the visible "reorganize itself" behavior),
5. snapshots metrics and records a frame.

Determinism is inherited from the seeded ``RandomSource`` tree: same scenario +
seed + strategy ⇒ identical recording (``RunRecording.digest``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ghost_commander.coordination import CoordinationStrategy, make_strategy
from ghost_commander.core import EventBus, EventLog, EventSeverity, EventType, RandomSource, SimClock
from ghost_commander.domain import AgentStatus, TaskStatus

from .failures import FailureModel
from .metrics import compute_metrics
from .recorder import RunRecording

if TYPE_CHECKING:
    from ghost_commander.domain import World

    from .scenario import Scenario

_RESOURCE_LOW_THRESHOLD = 0.2


class Simulation:
    def __init__(
        self,
        scenario: Scenario,
        strategy: CoordinationStrategy | str,
        record: bool = True,
    ) -> None:
        self.scenario = scenario
        self.strategy: CoordinationStrategy = (
            make_strategy(strategy) if isinstance(strategy, str) else strategy
        )
        self.root = RandomSource(seed=scenario.seed, label="/")
        self.clock = SimClock()
        self.bus = EventBus()
        self.log = EventLog()
        self.log.attach(self.bus)
        self.world: World = scenario.build_world(self.root)
        self.failures = FailureModel(scenario, self.root)

        self._record = record
        self.recording = RunRecording.from_scenario(scenario, self.strategy.name)
        if record:
            self.bus.subscribe_all(self.recording.add_event)

        self.reassignments = 0
        self._disrupted: set[int] = set()
        self._low_warned: set[int] = set()
        self._finished = False

        self.bus.emit(
            EventType.SIM_START,
            source="engine",
            sim_tick=0,
            strategy=self.strategy.name,
            scenario=scenario.name,
            n_agents=scenario.n_agents,
            n_tasks=scenario.n_tasks,
            seed=scenario.seed,
        )

    # ------------------------------------------------------------------ run
    def run(self) -> RunRecording:
        """Run until every task is done or ``max_ticks`` is reached."""
        # record the initial frame (tick 0) before any motion
        self._snapshot()
        while not self._finished and self.clock.tick < self.scenario.max_ticks:
            self.step()
        if not self._finished:
            self.bus.emit(
                EventType.MISSION_DEGRADED,
                source="engine",
                sim_tick=self.clock.tick,
                severity=EventSeverity.WARN,
                completion=round(self._completion(), 4),
                reason="max_ticks_reached",
            )
        return self.recording

    def step(self) -> None:
        tick = self.clock.advance()
        self._reassign(tick)
        self._advance_agents(tick)
        self._apply_failures(tick)
        self._snapshot()
        if self._all_done():
            self.bus.emit(
                EventType.MISSION_COMPLETE,
                source="engine",
                sim_tick=tick,
                tasks=self.world.tasks_total,
                agents_lost=self.scenario.n_agents - self.world.agents_alive,
                reassignments=self.reassignments,
            )
            self._finished = True

    # -------------------------------------------------------------- phases
    def _reassign(self, tick: int) -> None:
        for agent_id, task_id in self.strategy.assign(self.world):
            agent = self.world.agents[agent_id]
            task = self.world.tasks[task_id]
            if not agent.available or not task.needs_more_agents:
                continue
            agent.task_id = task_id
            agent.status = AgentStatus.MOVING
            task.assigned.add(agent_id)
            if task.status is TaskStatus.PENDING:
                task.status = TaskStatus.ASSIGNED
            if task_id in self._disrupted:
                self.reassignments += 1
                self._disrupted.discard(task_id)
                self.bus.emit(
                    EventType.TASK_REASSIGNED,
                    source="commander",
                    sim_tick=tick,
                    task=task_id,
                    agent=agent_id,
                    priority=int(task.priority),
                )
            else:
                self.bus.emit(
                    EventType.TASK_ASSIGNED,
                    source="commander",
                    sim_tick=tick,
                    severity=EventSeverity.DEBUG,
                    task=task_id,
                    agent=agent_id,
                    priority=int(task.priority),
                )

    def _advance_agents(self, tick: int) -> None:
        for agent in self.world.alive_agents():
            if agent.task_id is None:
                continue
            task = self.world.tasks[agent.task_id]
            if not task.open:
                self.world.unassign_agent(agent)
                continue
            arrived = agent.move_toward(task.x, task.y)
            if not arrived:
                agent.status = AgentStatus.MOVING
                continue
            # at the task: work it down
            agent.status = AgentStatus.WORKING
            if task.status is TaskStatus.ASSIGNED:
                task.status = TaskStatus.IN_PROGRESS
            task.remaining -= agent.capacity
            agent.work_done += agent.capacity
            if task.remaining <= 0.0:
                self._complete_task(task, tick)

    def _complete_task(self, task, tick: int) -> None:  # noqa: ANN001
        task.remaining = 0.0
        task.status = TaskStatus.DONE
        task.done_tick = tick
        freed = sorted(task.assigned)
        for aid in freed:
            ag = self.world.agents[aid]
            ag.task_id = None
            if ag.alive:
                ag.status = AgentStatus.IDLE
        task.assigned.clear()
        self.bus.emit(
            EventType.TASK_COMPLETED,
            source="commander",
            sim_tick=tick,
            task=task.id,
            priority=int(task.priority),
            freed_agents=freed,
        )

    def _apply_failures(self, tick: int) -> None:
        # resource-low warnings (before drain pushes them over the edge)
        for agent in self.world.alive_agents():
            if (
                agent.resources <= _RESOURCE_LOW_THRESHOLD
                and agent.id not in self._low_warned
            ):
                self._low_warned.add(agent.id)
                self.bus.emit(
                    EventType.AGENT_RESOURCE_LOW,
                    source="telemetry",
                    sim_tick=tick,
                    severity=EventSeverity.WARN,
                    agent=agent.id,
                    resources=round(agent.resources, 3),
                )

        for death in self.failures.apply(self.world, tick):
            agent = self.world.agents[death.agent_id]
            task = self.world.task_of(agent)
            if task is not None and task.open:
                self._disrupted.add(task.id)
            self.world.unassign_agent(agent)  # agent is FAILED; rolls task back
            self.bus.emit(
                EventType.AGENT_FAILED,
                source="telemetry",
                sim_tick=tick,
                severity=EventSeverity.ERROR if death.kind == "shock" else EventSeverity.WARN,
                agent=death.agent_id,
                kind=death.kind,
                task=task.id if task is not None else None,
            )

    # ------------------------------------------------------------- helpers
    def _snapshot(self) -> None:
        metrics = compute_metrics(self.world, self.clock.tick, self.reassignments)
        if self._record:
            self.recording.add_frame(self.clock.tick, self.world, metrics)

    def _all_done(self) -> bool:
        return all(t.status is TaskStatus.DONE for t in self.world.tasks.values())

    def _completion(self) -> float:
        total = sum(int(t.priority) for t in self.world.tasks.values()) or 1
        done = sum(
            int(t.priority) for t in self.world.tasks.values() if t.status is TaskStatus.DONE
        )
        return done / total


def run_scenario(scenario: Scenario, strategy: str, record: bool = True) -> RunRecording:
    """One-call helper used by the CLI, comparison tooling and tests."""
    return Simulation(scenario, strategy, record=record).run()


__all__ = ["Simulation", "run_scenario"]
