"""Head-to-head comparison of coordination strategies.

Inspired by Project Ghost's ``analysis.comparison``: hold the scenario and seed
fixed, vary only the strategy, and report the deltas. Because every run is
deterministic, the comparison is fair and reproducible — the difference you see
is the algorithm, nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ghost_commander.coordination import STRATEGIES

from .engine import run_scenario

if TYPE_CHECKING:
    from .recorder import RunRecording
    from .scenario import Scenario


@dataclass(frozen=True)
class StrategyResult:
    strategy: str
    completion: float
    tasks_done: int
    tasks_failed: int
    tasks_total: int
    ticks_to_finish: int | None
    agents_lost: int
    reassignments: int
    digest: str

    @classmethod
    def from_recording(cls, rec: RunRecording) -> StrategyResult:
        m = rec.final_metrics
        ticks_to_finish = None
        for snap in rec.metrics_history:
            # mission settles when no task is open anymore (done or failed)
            if snap["tasks_done"] + snap.get("tasks_failed", 0) == snap["tasks_total"]:
                ticks_to_finish = int(snap["tick"])
                break
        return cls(
            strategy=rec.strategy,
            completion=float(m.get("mission_completion", 0.0)),
            tasks_done=int(m.get("tasks_done", 0)),
            tasks_failed=int(m.get("tasks_failed", 0)),
            tasks_total=int(m.get("tasks_total", 0)),
            ticks_to_finish=ticks_to_finish,
            agents_lost=int(m.get("agents_total", 0)) - int(m.get("agents_alive", 0)),
            reassignments=int(m.get("reassignments", 0)),
            digest=rec.digest(),
        )


def compare_strategies(
    scenario: Scenario, strategies: list[str] | None = None, replan: bool = False
) -> list[StrategyResult]:
    names = strategies or list(STRATEGIES)
    results: list[StrategyResult] = []
    for name in names:
        rec = run_scenario(scenario, name, replan=replan)
        results.append(StrategyResult.from_recording(rec))
    # rank: highest completion, then fewest ticks, then fewest reassignments
    results.sort(
        key=lambda r: (-r.completion, r.ticks_to_finish or 10**9, r.reassignments)
    )
    return results


__all__ = ["StrategyResult", "compare_strategies"]
