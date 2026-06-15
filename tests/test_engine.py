"""Engine integration: missions complete, failures trigger reassignment, events flow."""

from __future__ import annotations

import pytest

from ghost_commander.coordination import STRATEGIES
from ghost_commander.core import EventType, RandomSource
from ghost_commander.sim import PRESETS, Scenario, Simulation, run_scenario


def test_calm_scenario_completes_all_tasks() -> None:
    # No failures, enough agents and ticks -> everything gets done.
    sc = Scenario(name="t", seed=3, n_agents=60, n_tasks=20, max_ticks=600,
                  random_failure_rate=0.0, shock_tick=None,
                  resource_drain_working=0.0, resource_drain_moving=0.0)
    rec = run_scenario(sc, "global")
    m = rec.final_metrics
    assert m["tasks_done"] == m["tasks_total"]
    assert m["mission_completion"] == 1.0


def test_shock_causes_failures_and_reassignments() -> None:
    sc = Scenario(seed=9, n_agents=100, n_tasks=40, shock_tick=10, shock_failure_rate=0.4,
                  max_ticks=500)
    rec = run_scenario(sc, "global")
    types = {e["type"] for e in rec.events}
    assert str(EventType.AGENT_FAILED) in types
    assert str(EventType.TASK_REASSIGNED) in types
    assert rec.final_metrics["reassignments"] > 0


def test_mission_complete_event_emitted_when_finished() -> None:
    sc = Scenario(seed=4, n_agents=80, n_tasks=10, max_ticks=800,
                  random_failure_rate=0.0, shock_tick=None, resource_drain_working=0.0)
    rec = run_scenario(sc, "auction")
    types = [e["type"] for e in rec.events]
    assert str(EventType.MISSION_COMPLETE) in types


def test_first_frame_is_initial_state() -> None:
    sim = Simulation(Scenario(seed=1, n_agents=30, n_tasks=10), "greedy")
    rec = sim.run()
    assert rec.frames[0]["tick"] == 0
    # initial frame: nothing done yet
    assert rec.frames[0]["metrics"]["tasks_done"] == 0


def test_no_deadlines_means_no_task_failures() -> None:
    # Default scenario has deadlines off -> tasks can never expire.
    rec = run_scenario(Scenario(seed=2, n_agents=80, n_tasks=20), "global")
    assert rec.final_metrics["tasks_failed"] == 0


def test_tight_deadline_under_attrition_fails_tasks() -> None:
    sc = Scenario(seed=2, n_agents=40, n_tasks=40, shock_tick=8, shock_failure_rate=0.5,
                  deadline_slack_factor=2.0, deadline_slack_base=6, max_ticks=300)
    rec = run_scenario(sc, "greedy")
    types = {e["type"] for e in rec.events}
    assert str(EventType.TASK_FAILED) in types
    assert rec.final_metrics["tasks_failed"] > 0
    # done + failed accounts for every task once the mission settles or times out
    m = rec.final_metrics
    assert m["tasks_done"] + m["tasks_failed"] <= m["tasks_total"]


def test_contested_preset_differentiates_strategies() -> None:
    # Coordination quality should change mission success, not just speed.
    sc = PRESETS["contested"]
    greedy = run_scenario(sc, "greedy").final_metrics
    glob = run_scenario(sc, "global").final_metrics
    assert glob["mission_completion"] >= greedy["mission_completion"]


def test_triage_wins_when_deadlines_are_tight() -> None:
    # Under the rush preset (tight, savable-if-triaged deadlines) the
    # deadline-aware strategy should beat all time-blind strategies.
    sc = PRESETS["rush"]
    triage = run_scenario(sc, "triage").final_metrics["mission_completion"]
    for blind in ("greedy", "auction", "global"):
        other = run_scenario(sc, blind).final_metrics["mission_completion"]
        assert triage >= other, f"triage {triage} should beat {blind} {other}"


def test_triage_without_deadlines_matches_global() -> None:
    # With deadlines off, triage's score reduces to global's -> identical run.
    sc = Scenario(seed=8, n_agents=60, n_tasks=25, shock_tick=10)
    assert run_scenario(sc, "triage").digest() == run_scenario(sc, "global").digest()


def test_dynamic_tasks_arrive_during_mission() -> None:
    sc = Scenario(seed=4, n_agents=60, n_tasks=10, dynamic_tasks=20,
                  arrival_start_tick=3, arrival_end_tick=40, max_ticks=400)
    rec = run_scenario(sc, "global")
    # the world grows from 10 to 30 tasks as objectives stream in
    assert rec.frames[0]["metrics"]["tasks_total"] == 10
    assert rec.final_metrics["tasks_total"] == 30
    created = [e for e in rec.events if e["type"] == str(EventType.TASK_CREATED)]
    assert len(created) == 20
    assert all(e["tick"] >= 3 for e in created)


def test_static_scenario_has_no_arrivals() -> None:
    sc = Scenario(seed=4, n_agents=40, n_tasks=15)  # dynamic_tasks defaults to 0
    rec = run_scenario(sc, "global")
    assert rec.final_metrics["tasks_total"] == 15
    assert not any(e["type"] == str(EventType.TASK_CREATED) for e in rec.events)


@pytest.mark.parametrize("strategy", list(STRATEGIES))
def test_specialization_is_always_respected(strategy: str) -> None:
    # No agent is ever assigned a task it lacks the skill for, across the run.
    sc = Scenario(seed=3, n_agents=40, n_tasks=40, shock_tick=8,
                  agent_skills=("a", "b", "c"))
    sim = Simulation(sc, strategy)
    original = sim._advance_agents

    def guarded(tick: int) -> None:
        for ag in sim.world.alive_agents():
            if ag.task_id is not None:
                t = sim.world.tasks[ag.task_id]
                assert ag.has_skill(t.required_skill), f"{ag.id} on wrong-skill {t.id}"
        original(tick)

    sim._advance_agents = guarded  # type: ignore[method-assign]
    sim.run()


def test_homogeneous_fleet_has_no_skill_requirements() -> None:
    sim = Simulation(Scenario(seed=1, n_agents=20, n_tasks=10), "global")
    assert all(not a.skills for a in sim.world.agents.values())
    assert all(t.required_skill is None for t in sim.world.tasks.values())


def test_recovery_sustains_the_fleet() -> None:
    # Same attritional mission with and without bases: recovery should keep far
    # more of the fleet alive and finish far more of the mission.
    import dataclasses

    base = PRESETS["endurance"]
    with_bases = run_scenario(base, "triage").final_metrics
    no_bases = run_scenario(dataclasses.replace(base, n_bases=0), "triage").final_metrics

    assert with_bases["recharges"] > 0
    assert no_bases["recharges"] == 0
    assert with_bases["agents_alive"] > no_bases["agents_alive"]
    assert with_bases["mission_completion"] > no_bases["mission_completion"] + 0.2


def test_no_bases_means_no_recharging() -> None:
    sim = Simulation(Scenario(seed=1, n_agents=30, n_tasks=15, resource_drain_working=0.05), "global")
    rec = sim.run()
    assert sim.world.bases == []
    assert rec.final_metrics["recharges"] == 0
    assert not any(e["type"] == str(EventType.AGENT_RECHARGING) for e in rec.events)


def test_cooperative_task_needs_the_full_team_present() -> None:
    from ghost_commander.domain import Agent, AgentStatus, Task, World

    sim = Simulation(Scenario(seed=1, n_agents=1, n_tasks=1), "global")
    # hand-build a controlled world: one 2-agent task, agents co-located on it
    world = World(width=10, height=10)
    world.add_task(Task(id=0, x=0.0, y=0.0, required_agents=2, workload=5.0))
    world.add_agent(Agent(id=0, x=0.0, y=0.0, capacity=1.0, task_id=0))
    world.add_agent(Agent(id=1, x=9.0, y=9.0, speed=0.0, capacity=1.0, task_id=0))
    world.tasks[0].assigned = {0, 1}
    sim.world = world

    # only agent 0 is on-site (agent 1 cannot move, speed 0) -> team incomplete
    sim._advance_agents(1)
    assert world.tasks[0].remaining == 5.0  # no progress without the full team
    assert world.agents[0].status is AgentStatus.WORKING  # present but waiting

    # bring the team together: agent 1 teleported on-site -> progress resumes
    world.agents[1].x, world.agents[1].y = 0.0, 0.0
    sim._advance_agents(2)
    assert world.tasks[0].remaining == 3.0  # both contributed 1.0 each


def test_joint_preset_has_team_tasks_and_differentiates() -> None:
    sim = Simulation(PRESETS["joint"], "global")
    sim.run()
    assert any(t.required_agents > 1 for t in sim.world.tasks.values())
    greedy = run_scenario(PRESETS["joint"], "greedy").final_metrics["mission_completion"]
    glob = run_scenario(PRESETS["joint"], "global").final_metrics["mission_completion"]
    assert glob >= greedy


def test_default_scenario_is_all_single_agent() -> None:
    sim = Simulation(Scenario(seed=2, n_agents=20, n_tasks=20), "global")
    assert all(t.required_agents == 1 for t in sim.world.tasks.values())


def test_replan_off_is_unchanged() -> None:
    # The default (replan off) must reproduce the exact same run as before.
    sc = Scenario(seed=3, n_agents=60, n_tasks=30, shock_tick=12)
    assert run_scenario(sc, "global").digest() == run_scenario(sc, "global", replan=False).digest()


def test_replan_helps_under_deadline_pressure() -> None:
    # Rescue preemption should save more of the mission when deadlines bite.
    for preset in ("rush", "specialist"):
        off = run_scenario(PRESETS[preset], "global").final_metrics["mission_completion"]
        on = run_scenario(PRESETS[preset], "global", replan=True).final_metrics["mission_completion"]
        assert on > off, f"{preset}: replan {on} should beat no-replan {off}"


def test_replan_is_deterministic() -> None:
    sc = PRESETS["rush"]
    assert run_scenario(sc, "global", replan=True).digest() == \
        run_scenario(sc, "global", replan=True).digest()


def test_replan_emits_rescue_reassignments() -> None:
    rec = run_scenario(PRESETS["rush"], "global", replan=True)
    rescues = [e for e in rec.events
               if e["type"] == str(EventType.TASK_REASSIGNED) and e.get("p_reason") == "rescue"]
    assert rescues, "expected at least one rescue preemption under tight deadlines"


def test_priority_escalates_over_time() -> None:
    from ghost_commander.domain import Task, TaskPriority

    t = Task(id=0, x=0, y=0, priority=TaskPriority.NORMAL, escalate_every=10, created_tick=0)
    assert t.priority_at(0) == 2
    assert t.priority_at(9) == 2
    assert t.priority_at(10) == 3
    assert t.priority_at(10_000) == int(TaskPriority.VITAL)  # capped
    static = Task(id=1, x=0, y=0, priority=TaskPriority.NORMAL)  # no escalation
    assert static.priority_at(10_000) == 2


def test_escalating_preset_runs_and_differentiates() -> None:
    greedy = run_scenario(PRESETS["escalating"], "greedy").final_metrics["mission_completion"]
    triage = run_scenario(PRESETS["escalating"], "triage").final_metrics["mission_completion"]
    assert triage >= greedy


def test_mixed_task_needs_each_required_skill() -> None:
    from ghost_commander.domain import Agent, Task, World

    sim = Simulation(Scenario(seed=1, n_agents=1, n_tasks=1), "global")
    world = World(width=10, height=10)
    world.add_task(Task(id=0, x=0.0, y=0.0, required_skills=("a", "b"), workload=5.0))
    # two agents of the SAME skill on-site -> the other skill is missing -> no progress
    world.add_agent(Agent(id=0, x=0.0, y=0.0, task_id=0, skills=frozenset({"a"})))
    world.add_agent(Agent(id=1, x=0.0, y=0.0, task_id=0, skills=frozenset({"a"})))
    world.tasks[0].assigned = {0, 1}
    sim.world = world
    sim._advance_agents(1)
    assert world.tasks[0].remaining == 5.0  # missing skill "b"
    # give agent 1 the missing skill -> both skills present -> progress
    world.agents[1].skills = frozenset({"b"})
    sim._advance_agents(2)
    assert world.tasks[0].remaining < 5.0


def test_taskforce_forms_and_completes_mixed_teams() -> None:
    from ghost_commander.domain import TaskStatus

    sim = Simulation(PRESETS["taskforce"], "global")
    sim.run()
    mixed = [t for t in sim.world.tasks.values() if t.required_skills]
    assert mixed, "taskforce should produce mixed-specialist tasks"
    assert any(t.status is TaskStatus.DONE for t in mixed)


@pytest.mark.parametrize("strategy", list(STRATEGIES))
def test_mixed_assignment_respects_skill_mix(strategy: str) -> None:
    # No agent is ever sent to a mixed task it can't contribute a needed skill to.
    sim = Simulation(PRESETS["taskforce"], strategy)
    original = sim._advance_agents

    def guarded(tick: int) -> None:
        for ag in sim.world.alive_agents():
            if ag.task_id is not None:
                t = sim.world.tasks[ag.task_id]
                if t.required_skills:
                    assert ag.skill in t.required_skills, f"{ag.id} on mixed task {t.id}"
        original(tick)

    sim._advance_agents = guarded  # type: ignore[method-assign]
    sim.run()


def test_heterogeneous_fleet_varies_capabilities() -> None:
    sim = Simulation(PRESETS["mixedfleet"], "global")
    speeds = {round(a.speed, 4) for a in sim.world.agents.values()}
    caps = {round(a.capacity, 4) for a in sim.world.agents.values()}
    assert len(speeds) > 5 and len(caps) > 5  # a genuinely varied fleet


def test_uniform_fleet_when_no_spread() -> None:
    sim = Simulation(Scenario(seed=2, n_agents=20, n_tasks=10, agent_speed=3.0), "global")
    assert {a.speed for a in sim.world.agents.values()} == {3.0}


def test_mixedfleet_runs_and_greedy_is_not_best() -> None:
    greedy = run_scenario(PRESETS["mixedfleet"], "greedy").final_metrics["mission_completion"]
    triage = run_scenario(PRESETS["mixedfleet"], "triage").final_metrics["mission_completion"]
    assert triage >= greedy


def test_locked_task_is_not_assignable_until_prereq_done() -> None:
    from ghost_commander.domain import Task, TaskStatus, World

    w = World(width=10, height=10)
    w.add_task(Task(id=0, x=1, y=1))                  # prerequisite
    w.add_task(Task(id=1, x=2, y=2, requires=(0,)))   # depends on task 0
    assert w.is_unlocked(w.tasks[0])
    assert not w.is_unlocked(w.tasks[1])
    assert w.needed_slots(w.tasks[1]) == []           # locked -> no slots
    assert w.tasks[1] not in w.assignable_tasks()
    w.tasks[0].status = TaskStatus.DONE               # clear the prerequisite
    assert w.is_unlocked(w.tasks[1])
    assert w.needed_slots(w.tasks[1]) == [None]       # now assignable
    assert w.tasks[1] in w.assignable_tasks()


def test_locked_task_does_not_fail_while_waiting() -> None:
    from ghost_commander.domain import Task, TaskStatus, World

    sim = Simulation(Scenario(seed=1, n_agents=1, n_tasks=1), "global")
    world = World(width=10, height=10)
    world.add_task(Task(id=0, x=1, y=1))  # never completed
    world.add_task(Task(id=1, x=2, y=2, requires=(0,), deadline_tick=1))
    sim.world = world
    sim._expire_overdue(100)  # well past the deadline
    assert world.tasks[1].status is not TaskStatus.FAILED  # locked -> can't fail


def test_phased_has_dependencies_and_no_precedence_by_default() -> None:
    phased = Simulation(PRESETS["phased"], "global")
    assert any(t.requires for t in phased.world.tasks.values())
    plain = Simulation(Scenario(seed=2, n_agents=20, n_tasks=15), "global")
    assert all(not t.requires for t in plain.world.tasks.values())


def test_recurring_task_revives_after_revisit_interval() -> None:
    from ghost_commander.domain import Task, TaskStatus, World

    sim = Simulation(Scenario(seed=1, n_agents=1, n_tasks=1), "global")
    world = World(width=10, height=10)
    world.add_task(Task(id=0, x=0.0, y=0.0, revisit_every=10, workload=5.0))
    sim.world = world
    world.tasks[0].status = TaskStatus.DONE
    world.tasks[0].done_tick = 100
    sim._revive_recurring(105)  # not yet due
    assert world.tasks[0].status is TaskStatus.DONE
    sim._revive_recurring(110)  # 10 ticks later -> revives
    assert world.tasks[0].status is TaskStatus.PENDING
    assert world.tasks[0].remaining == 5.0


def test_monitor_keeps_coverage_and_greedy_is_worst() -> None:
    import statistics as st

    def mean_cov(strat: str) -> float:
        h = run_scenario(PRESETS["monitor"], strat).metrics_history
        return st.mean(s["coverage"] for s in h)

    greedy, triage = mean_cov("greedy"), mean_cov("triage")
    assert 0.0 < greedy < triage  # coverage is partial, and greedy is worse


def test_non_recurring_coverage_is_full() -> None:
    rec = run_scenario(Scenario(seed=1, n_agents=40, n_tasks=20), "global")
    assert all(s["coverage"] == 1.0 for s in rec.metrics_history)


def test_workload_uncertainty_splits_estimate_from_truth() -> None:
    # With uncertainty on, the true workload differs from the briefed estimate,
    # so at least some tasks carry an estimate distinct from their real workload.
    sc = Scenario(seed=7, n_agents=10, n_tasks=40, workload_uncertainty=0.5)
    world = sc.build_world(RandomSource(seed=sc.seed, label="/"))
    tasks = list(world.tasks.values())
    assert any(t.estimated_workload is not None for t in tasks)
    for t in tasks:
        if t.estimated_workload is not None:
            assert t.workload >= 0.5  # true workload is floored, never zero


def test_no_uncertainty_means_perfect_information() -> None:
    # Default (uncertainty 0): the estimate is never recorded — plain remaining
    # is used for planning, exactly as before the feature existed.
    sc = Scenario(seed=7, n_agents=10, n_tasks=40)
    world = sc.build_world(RandomSource(seed=sc.seed, label="/"))
    assert all(t.estimated_workload is None for t in world.tasks.values())


def test_uncertainty_is_opt_in_and_changes_the_run() -> None:
    # The feature is opt-in: enabling it draws an extra workload RNG per task, so
    # the run differs from the perfect-information baseline. (When off it draws
    # nothing extra, keeping every existing scenario's digest stable.)
    import dataclasses
    base = Scenario(seed=11, n_agents=40, n_tasks=30, shock_tick=20)
    foggy = dataclasses.replace(base, workload_uncertainty=0.5)
    assert run_scenario(base, "triage").digest() != \
        run_scenario(foggy, "triage").digest()


def test_fog_preset_runs_and_completes_mostly() -> None:
    rec = run_scenario(PRESETS["fog"], "triage")
    m = rec.final_metrics
    assert m["tasks_total"] == PRESETS["fog"].n_tasks
    assert 0.5 < m["mission_completion"] <= 1.0


def test_compare_robust_distribution() -> None:
    from ghost_commander.sim import compare_robust

    res = compare_robust(PRESETS["rush"], seeds=[42, 11, 7])
    assert len(res) == len(STRATEGIES)
    for r in res:
        assert r.n == 3 and 0 <= r.wins <= 3 and 0.0 <= r.mean <= 1.0001
        assert r.lo <= r.mean <= r.hi
    assert all(res[i].mean >= res[i + 1].mean for i in range(len(res) - 1))  # sorted
    assert sum(r.wins for r in res) >= 3  # at least one winner per seed


def test_sweep_scales_with_fleet_size() -> None:
    from ghost_commander.sim import sweep

    data = sweep(PRESETS["rush"], "agents", [30, 60, 90], strategies=["greedy", "triage"])
    assert set(data) == {"greedy", "triage"}
    for name in data:
        xs = [v for v, _ in data[name]]
        assert xs == [30.0, 60.0, 90.0]
        assert all(0.0 <= m <= 1.0001 for _, m in data[name])
    # more fleet -> generally more mission for triage (monotone-ish at these points)
    ys = [m for _, m in data["triage"]]
    assert ys[-1] >= ys[0]


def test_sweep_rejects_unknown_param() -> None:
    from ghost_commander.sim import sweep

    with pytest.raises(ValueError):
        sweep(PRESETS["rush"], "nonsense", [1, 2])


def test_saved_run_verifies_and_tamper_is_detected(tmp_path) -> None:  # noqa: ANN001
    import json

    from ghost_commander.sim import verify_run

    # a custom (non-preset) scenario, saved and re-verified from the file alone
    sc = Scenario(seed=9, n_agents=30, n_tasks=25, shock_tick=8,
                  deadline_slack_factor=3.0, deadline_slack_base=12)
    path = tmp_path / "run.json"
    run_scenario(sc, "triage").save(str(path))

    ok, saved, got = verify_run(str(path))
    assert ok and saved == got

    # tamper with the recorded digest -> verification must fail
    d = json.loads(path.read_text())
    d["digest"] = "deadbeefdeadbeef"
    path.write_text(json.dumps(d))
    ok2, _, _ = verify_run(str(path))
    assert not ok2
