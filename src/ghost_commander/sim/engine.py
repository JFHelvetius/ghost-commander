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
from ghost_commander.coordination.base import can_fill, urgency_score
from ghost_commander.core import EventBus, EventLog, EventSeverity, EventType, RandomSource, SimClock
from ghost_commander.domain import AgentStatus, TaskStatus

from .failures import FailureModel
from .metrics import compute_metrics
from .recorder import RunRecording

if TYPE_CHECKING:
    from ghost_commander.domain import World

    from .scenario import Scenario

_RESOURCE_LOW_THRESHOLD = 0.2
# Continuous re-planning ("rescue preemption"). To stay net-positive and avoid
# thrashing, an en-route agent is only pulled onto another task when ALL hold:
#  - the alternative is at least this much better (hysteresis), and
#  - the agent isn't about to arrive at its current target (arrival guard, ticks), and
#  - the alternative is deadline-bound and genuinely at risk (savable but tight), and
#  - its current task isn't itself an at-risk rescue that depends on it.
_REPLAN_HYSTERESIS = 0.5
_REPLAN_ARRIVAL_GUARD = 4
_REPLAN_RISK_WINDOW = 12


def _spare_ticks(agent, task, tick: int) -> int | None:  # noqa: ANN001
    """Slack minus estimated time-to-complete; None if the task has no deadline."""
    import math

    if task.deadline_tick is None:
        return None
    d = agent.distance_to(task.x, task.y)
    ttc = math.ceil(d / max(agent.speed, 1e-6)) + math.ceil(
        max(task.remaining, 0.0) / max(agent.capacity, 1e-6)
    )
    return (task.deadline_tick - tick) - ttc


class Simulation:
    def __init__(
        self,
        scenario: Scenario,
        strategy: CoordinationStrategy | str,
        record: bool = True,
        replan: bool = False,
    ) -> None:
        self.scenario = scenario
        self.replan = replan
        self.strategy: CoordinationStrategy = (
            make_strategy(strategy) if isinstance(strategy, str) else strategy
        )
        self.root = RandomSource(seed=scenario.seed, label="/")
        self.clock = SimClock()
        self.bus = EventBus()
        self.log = EventLog()
        self.log.attach(self.bus)
        self.world: World = scenario.build_world(self.root)
        # tasks that arrive *during* the mission (sorted by spawn tick)
        self._arrivals = scenario.schedule_arrivals(self.root)
        self._next_arrival = 0
        self.failures = FailureModel(scenario, self.root)

        self._record = record
        self.recording = RunRecording.from_scenario(scenario, self.strategy.name)
        if record:
            self.bus.subscribe_all(self.recording.add_event)

        self.reassignments = 0
        self._recharges = 0
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
        self.world.tick = tick
        self._spawn_arrivals(tick)
        self._manage_recharge(tick)
        if self.replan:
            self._replan(tick)
        self._reassign(tick)
        self._advance_agents(tick)
        self._apply_failures(tick)
        self._expire_overdue(tick)
        self._snapshot()
        if self._settled():
            self._finish(tick)

    # -------------------------------------------------------------- phases
    def _replan(self, tick: int) -> None:
        """Continuous re-planning via *rescue preemption*: each tick, redirect an
        en-route agent to a task that is about to expire — but only when it pays.
        Working agents are never disturbed (don't waste their trip); the strict
        guards (hysteresis, arrival guard, at-risk-only target, don't-abandon-a-
        rescue) keep it net-positive and thrash-free. This is what makes the
        reassignment genuinely *dynamic*: the committed fleet is re-evaluated every
        tick, not only when a failure frees a task."""
        for agent in sorted(self.world.alive_agents(), key=lambda a: a.id):
            if agent.status is not AgentStatus.MOVING or agent.task_id is None:
                continue
            current = self.world.tasks[agent.task_id]
            if not current.open:
                continue
            # about to arrive -> let it finish the trip
            if agent.distance_to(current.x, current.y) <= _REPLAN_ARRIVAL_GUARD * agent.speed:
                continue
            # don't abandon a task that is itself an at-risk rescue depending on me
            cur_spare = _spare_ticks(agent, current, tick)
            if (cur_spare is not None and 0 <= cur_spare <= _REPLAN_RISK_WINDOW
                    and len(current.assigned) <= current.required_agents):
                continue
            keep = urgency_score(agent, current, tick) * (1.0 + _REPLAN_HYSTERESIS)
            best, best_s = None, keep
            for task in self.world.assignable_tasks():
                if task.id == current.id or not can_fill(self.world.needed_slots(task), agent):
                    continue
                spare = _spare_ticks(agent, task, tick)
                if spare is None or spare < 0 or spare > _REPLAN_RISK_WINDOW:
                    continue  # rescue-only: must be deadline-bound, savable and tight
                s = urgency_score(agent, task, tick)
                if s > best_s or (s == best_s and (best is None or task.id < best.id)):
                    best, best_s = task, s
            if best is None:
                continue
            # preempt: leave the current task (freeing a slot), rush the at-risk one
            current.assigned.discard(agent.id)
            if not current.assigned and current.status in (
                TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS
            ):
                current.status = TaskStatus.PENDING
            agent.task_id = best.id
            best.assigned.add(agent.id)
            if best.status is TaskStatus.PENDING:
                best.status = TaskStatus.ASSIGNED
            self.reassignments += 1
            self.bus.emit(
                EventType.TASK_REASSIGNED,
                source="commander",
                sim_tick=tick,
                task=best.id,
                agent=agent.id,
                from_task=current.id,
                reason="rescue",
                priority=int(best.priority),
            )

    def _reassign(self, tick: int) -> None:
        for agent_id, task_id in self.strategy.assign(self.world):
            agent = self.world.agents[agent_id]
            task = self.world.tasks[task_id]
            if not agent.available or not can_fill(self.world.needed_slots(task), agent):
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
        # Phase 1: move every assigned agent toward its task; mark who is on-site.
        for agent in self.world.alive_agents():
            if agent.task_id is None:
                continue
            task = self.world.tasks[agent.task_id]
            if not task.open:
                self.world.unassign_agent(agent)
                continue
            arrived = agent.move_toward(task.x, task.y)
            agent.status = AgentStatus.WORKING if arrived else AgentStatus.MOVING

        # Phase 2: apply work per task. A cooperative task (required_agents > 1)
        # only progresses once the *whole team* is on-site — agents that arrive
        # early wait (WORKING, but no progress), which is the synchronization
        # cost the commander must manage. Single-agent tasks behave exactly as
        # before, so existing scenarios are byte-identical.
        for task in list(self.world.tasks.values()):
            if not task.open:
                continue
            present = [
                self.world.agents[aid]
                for aid in sorted(task.assigned)
                if self.world.agents[aid].status is AgentStatus.WORKING
            ]
            if task.required_skills:
                # mixed task: progresses only once every required skill is on-site
                present_skills = {a.skill for a in present}
                if not all(s in present_skills for s in task.required_skills):
                    continue
            elif len(present) < task.required_agents:
                continue  # team incomplete -> no progress this tick
            if task.status is TaskStatus.ASSIGNED:
                task.status = TaskStatus.IN_PROGRESS
            for agent in present:
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

    def _manage_recharge(self, tick: int) -> None:
        """Route depleted agents to bases and refuel those already there.

        A low agent is pulled off its task (freeing it for reassignment), heads
        to the nearest base, regains resources, and rejoins the pool — turning
        attrition into a logistics problem the commander can manage. No-op when
        the scenario has no bases.
        """
        if not self.world.bases:
            return
        sc = self.scenario
        for agent in self.world.alive_agents():
            if agent.status is AgentStatus.RECHARGING:
                base = self.world.nearest_base(agent.x, agent.y)
                assert base is not None  # bases is non-empty here
                if agent.move_toward(*base):
                    agent.resources = min(sc.recharge_target, agent.resources + sc.recharge_rate)
                    if agent.resources >= sc.recharge_target:
                        agent.status = AgentStatus.IDLE
                        self.bus.emit(
                            EventType.AGENT_RECOVERED,
                            source="logistics",
                            sim_tick=tick,
                            agent=agent.id,
                        )
            elif agent.resources <= sc.recharge_threshold:
                task = self.world.task_of(agent)
                if task is not None and task.open:
                    self._disrupted.add(task.id)
                self.world.unassign_agent(agent)  # -> IDLE
                agent.status = AgentStatus.RECHARGING
                self._recharges += 1
                self.bus.emit(
                    EventType.AGENT_RECHARGING,
                    source="logistics",
                    sim_tick=tick,
                    agent=agent.id,
                    resources=round(agent.resources, 3),
                )

    def _spawn_arrivals(self, tick: int) -> None:
        """Inject any tasks whose spawn tick has arrived — a changing world."""
        while self._next_arrival < len(self._arrivals):
            task = self._arrivals[self._next_arrival]
            if task.created_tick > tick:
                break
            self.world.add_task(task)
            self._next_arrival += 1
            self.bus.emit(
                EventType.TASK_CREATED,
                source="environment",
                sim_tick=tick,
                task=task.id,
                priority=int(task.priority),
                deadline=task.deadline_tick,
            )

    @property
    def _arrivals_pending(self) -> bool:
        return self._next_arrival < len(self._arrivals)

    def _expire_overdue(self, tick: int) -> None:
        """Fail any open task whose deadline has passed — a mission loss."""
        for task in self.world.tasks.values():
            if not task.open or not task.is_overdue(tick):
                continue
            task.status = TaskStatus.FAILED
            task.failed_tick = tick
            freed = sorted(task.assigned)
            for aid in freed:
                ag = self.world.agents[aid]
                ag.task_id = None
                if ag.alive:
                    ag.status = AgentStatus.IDLE
            task.assigned.clear()
            self._disrupted.discard(task.id)
            self.bus.emit(
                EventType.TASK_FAILED,
                source="commander",
                sim_tick=tick,
                severity=EventSeverity.ERROR if task.priority >= 4 else EventSeverity.WARN,
                task=task.id,
                priority=int(task.priority),
                progress=round(task.progress, 3),
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
        metrics = compute_metrics(
            self.world, self.clock.tick, self.reassignments, self._recharges
        )
        if self._record:
            self.recording.add_frame(self.clock.tick, self.world, metrics)

    def _settled(self) -> bool:
        """Mission over: no open tasks left AND no more tasks will arrive."""
        if self._arrivals_pending:
            return False
        return not any(t.open for t in self.world.tasks.values())

    def _all_done(self) -> bool:
        return all(t.status is TaskStatus.DONE for t in self.world.tasks.values())

    def _finish(self, tick: int) -> None:
        self._finished = True
        failed = sum(1 for t in self.world.tasks.values() if t.status is TaskStatus.FAILED)
        if failed == 0:
            self.bus.emit(
                EventType.MISSION_COMPLETE,
                source="engine",
                sim_tick=tick,
                tasks=self.world.tasks_total,
                agents_lost=self.scenario.n_agents - self.world.agents_alive,
                reassignments=self.reassignments,
            )
        else:
            self.bus.emit(
                EventType.MISSION_DEGRADED,
                source="engine",
                sim_tick=tick,
                severity=EventSeverity.WARN,
                completion=round(self._completion(), 4),
                tasks_failed=failed,
                agents_lost=self.scenario.n_agents - self.world.agents_alive,
                reason="tasks_expired",
            )

    def _completion(self) -> float:
        total = sum(int(t.priority) for t in self.world.tasks.values()) or 1
        done = sum(
            int(t.priority) for t in self.world.tasks.values() if t.status is TaskStatus.DONE
        )
        return done / total


def run_scenario(
    scenario: Scenario, strategy: str, record: bool = True, replan: bool = False
) -> RunRecording:
    """One-call helper used by the CLI, comparison tooling and tests."""
    return Simulation(scenario, strategy, record=record, replan=replan).run()


__all__ = ["Simulation", "run_scenario"]
