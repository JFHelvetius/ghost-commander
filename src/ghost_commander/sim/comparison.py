"""Head-to-head comparison of coordination strategies.

Inspired by Project Ghost's ``analysis.comparison``: hold the scenario and seed
fixed, vary only the strategy, and report the deltas. Because every run is
deterministic, the comparison is fair and reproducible — the difference you see
is the algorithm, nothing else.
"""

from __future__ import annotations

import dataclasses
import json
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ghost_commander.coordination import STRATEGIES

from .engine import run_scenario
from .scenario import Scenario

if TYPE_CHECKING:
    from .recorder import RunRecording


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
    mean_coverage: float  # time-average coverage (for recurring/monitoring runs)
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
        hist = rec.metrics_history
        mean_cov = (sum(s.get("coverage", 1.0) for s in hist) / len(hist)) if hist else 1.0
        return cls(
            strategy=rec.strategy,
            completion=float(m.get("mission_completion", 0.0)),
            tasks_done=int(m.get("tasks_done", 0)),
            tasks_failed=int(m.get("tasks_failed", 0)),
            tasks_total=int(m.get("tasks_total", 0)),
            ticks_to_finish=ticks_to_finish,
            agents_lost=int(m.get("agents_total", 0)) - int(m.get("agents_alive", 0)),
            reassignments=int(m.get("reassignments", 0)),
            mean_coverage=mean_cov,
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
    if scenario.revisit_every > 0:
        # persistent monitoring: rank by maintained coverage, not completion
        results.sort(key=lambda r: (-r.mean_coverage, r.reassignments))
    else:
        results.sort(key=lambda r: (-r.completion, r.ticks_to_finish or 10**9, r.reassignments))
    return results


@dataclass(frozen=True)
class RobustResult:
    """A strategy's headline metric distribution across many seeds."""

    strategy: str
    mean: float
    std: float
    lo: float
    hi: float
    wins: int   # seeds where this strategy was (tied) best
    n: int      # number of seeds

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0


def _headline(rec: RunRecording, recurring: bool) -> float:
    if recurring:
        h = rec.metrics_history
        return sum(s.get("coverage", 1.0) for s in h) / len(h) if h else 1.0
    return float(rec.final_metrics.get("mission_completion", 0.0))


def compare_robust(
    scenario: Scenario, seeds: list[int], strategies: list[str] | None = None,
    replan: bool = False,
) -> list[RobustResult]:
    """Run every strategy over many seeds and report the distribution of the
    headline metric (mission % or, for recurring scenarios, mean coverage). This
    is the honest way to read the comparison: a single seed can mislead.
    """
    names = strategies or list(STRATEGIES)
    recurring = scenario.revisit_every > 0
    per: dict[str, list[float]] = {n: [] for n in names}
    wins: dict[str, int] = {n: 0 for n in names}
    for s in seeds:
        sc = dataclasses.replace(scenario, seed=s)
        vals = {n: _headline(run_scenario(sc, n, replan=replan), recurring) for n in names}
        best = max(vals.values())
        for n, v in vals.items():
            per[n].append(v)
            if v >= best - 1e-9:
                wins[n] += 1
    out = [
        RobustResult(
            strategy=n, mean=statistics.mean(per[n]),
            std=statistics.pstdev(per[n]) if len(per[n]) > 1 else 0.0,
            lo=min(per[n]), hi=max(per[n]), wins=wins[n], n=len(seeds),
        )
        for n in names
    ]
    out.sort(key=lambda r: -r.mean)
    return out


# Parameters a sensitivity sweep can vary: name -> (Scenario field, label).
SWEEP_PARAMS: dict[str, tuple[str, str]] = {
    "agents": ("n_agents", "nº de unidades"),
    "tasks": ("n_tasks", "nº de tareas"),
    "speed": ("agent_speed", "velocidad de las unidades"),
    "deadline": ("deadline_slack_base", "holgura de plazo"),
}


def sweep(
    scenario: Scenario, param: str, values: list[float],
    strategies: list[str] | None = None, seeds: int = 1, replan: bool = False,
) -> dict[str, list[tuple[float, float]]]:
    """Vary one scenario parameter and report the headline metric per strategy.

    Answers the planning question the comparison can't: *how does the outcome
    scale?* — e.g. how much fleet each strategy needs to hit a target. Returns
    ``{strategy: [(value, mean_metric), ...]}``; averaged over ``seeds``.
    """
    if param not in SWEEP_PARAMS:
        raise ValueError(f"unknown sweep param {param!r}; choices: {', '.join(SWEEP_PARAMS)}")
    field = SWEEP_PARAMS[param][0]
    names = strategies or list(STRATEGIES)
    recurring = scenario.revisit_every > 0
    out: dict[str, list[tuple[float, float]]] = {n: [] for n in names}
    for v in values:
        cast = type(getattr(scenario, field))
        base = dataclasses.replace(scenario, **{field: cast(v)})
        for n in names:
            vals = [
                _headline(run_scenario(
                    dataclasses.replace(base, seed=scenario.seed + s), n, replan=replan),
                    recurring)
                for s in range(seeds)
            ]
            out[n].append((float(v), statistics.mean(vals)))
    return out


def verify_run(path: str) -> tuple[bool, str, str]:
    """Re-run a saved recording from scratch and check its determinism digest.

    A saved run carries the full scenario, so a third party can re-create and
    re-execute it from the file alone and confirm the result is reproducible
    byte-for-byte. Returns ``(matches, saved_digest, recomputed_digest)``.
    """
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    params = d.get("scenario_params")
    if not params:
        raise ValueError("recording has no scenario_params (saved by an older version)")
    scenario = Scenario(**{
        k: tuple(v) if isinstance(v, list) else v for k, v in params.items()
    })
    rec = run_scenario(scenario, d["strategy"], replan=d.get("replan", False))
    saved = str(d.get("digest", ""))
    return rec.digest() == saved, saved, rec.digest()


__all__ = [
    "SWEEP_PARAMS",
    "RobustResult",
    "StrategyResult",
    "compare_robust",
    "compare_strategies",
    "sweep",
    "verify_run",
]
