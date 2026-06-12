"""Headless demo: run the default scenario with each strategy and compare.

    python examples/run_demo.py
"""

from __future__ import annotations

from ghost_commander.sim import Scenario, compare_strategies, run_scenario


def main() -> None:
    scenario = Scenario(name="demo", seed=7, n_agents=100, n_tasks=55, shock_tick=18)

    print("=== single run (global strategy) ===")
    rec = run_scenario(scenario, "global")
    m = rec.final_metrics
    print(f"  mission completion : {m['mission_completion']*100:.1f}%")
    print(f"  tasks done         : {m['tasks_done']}/{m['tasks_total']}")
    print(f"  agents lost        : {m['agents_total']-m['agents_alive']}")
    print(f"  reassignments      : {m['reassignments']}")
    print(f"  determinism digest : {rec.digest()}")

    print("\n=== strategy comparison (same scenario + seed) ===")
    for i, r in enumerate(compare_strategies(scenario), start=1):
        ticks = "—" if r.ticks_to_finish is None else r.ticks_to_finish
        print(f"  {i}. {r.strategy:<8} mission={r.completion*100:5.1f}%  "
              f"done={r.tasks_done}/{r.tasks_total}  ticks={ticks}  "
              f"lost={r.agents_lost}  reassign={r.reassignments}")


if __name__ == "__main__":
    main()
