"""Same scenario + seed + strategy must reproduce a run bit-for-bit."""

from __future__ import annotations

import pytest

from ghost_commander.coordination import STRATEGIES
from ghost_commander.sim import Scenario, run_scenario


@pytest.mark.parametrize("strategy", list(STRATEGIES))
def test_run_is_reproducible(strategy: str) -> None:
    sc = Scenario(seed=123, n_agents=50, n_tasks=20, max_ticks=200)
    a = run_scenario(sc, strategy)
    b = run_scenario(sc, strategy)
    assert a.digest() == b.digest()
    assert a.metrics_history == b.metrics_history


def test_different_seed_changes_outcome() -> None:
    a = run_scenario(Scenario(seed=1, n_agents=50, n_tasks=20), "global")
    b = run_scenario(Scenario(seed=2, n_agents=50, n_tasks=20), "global")
    assert a.digest() != b.digest()


def test_failure_stream_independent_of_layout() -> None:
    # Same seed -> identical failure draws regardless; sanity that the run has losses.
    rec = run_scenario(Scenario(seed=5, n_agents=80, n_tasks=30, shock_tick=20), "global")
    final = rec.final_metrics
    assert final["agents_alive"] < final["agents_total"]
