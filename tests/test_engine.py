"""Engine integration: missions complete, failures trigger reassignment, events flow."""

from __future__ import annotations

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
