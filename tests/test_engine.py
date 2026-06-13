"""Engine integration: missions complete, failures trigger reassignment, events flow."""

from __future__ import annotations

import pytest

from ghost_commander.coordination import STRATEGIES
from ghost_commander.core import EventType
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
