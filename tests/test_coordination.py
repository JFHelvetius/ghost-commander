"""Strategy behavior: valid assignments, contention handling, no over-fill."""

from __future__ import annotations

import pytest

from ghost_commander.coordination import STRATEGIES, make_strategy
from ghost_commander.domain import Agent, Task, TaskPriority, World


def _world() -> World:
    w = World(width=100, height=100)
    w.add_agent(Agent(id=0, x=0, y=0))
    w.add_agent(Agent(id=1, x=100, y=100))
    w.add_task(Task(id=0, x=5, y=5, priority=TaskPriority.LOW))
    w.add_task(Task(id=1, x=95, y=95, priority=TaskPriority.VITAL))
    return w


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_assignments_are_valid(name: str) -> None:
    strat = make_strategy(name)
    w = _world()
    pairs = strat.assign(w)
    seen_agents = set()
    for agent_id, task_id in pairs:
        assert agent_id in w.agents
        assert task_id in w.tasks
        assert agent_id not in seen_agents  # no agent assigned twice in one round
        seen_agents.add(agent_id)


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_does_not_overfill_single_agent_task(name: str) -> None:
    strat = make_strategy(name)
    w = World(width=10, height=10)
    for i in range(5):
        w.add_agent(Agent(id=i, x=i, y=0))
    w.add_task(Task(id=0, x=0, y=0, required_agents=1))
    pairs = strat.assign(w)
    assigned_to_task0 = [a for a, t in pairs if t == 0]
    assert len(assigned_to_task0) <= 1


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_assignment_is_deterministic(name: str) -> None:
    assert make_strategy(name).assign(_world()) == make_strategy(name).assign(_world())


def test_unknown_strategy_raises() -> None:
    with pytest.raises(ValueError):
        make_strategy("does-not-exist")
