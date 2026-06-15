"""Command-line entry point for headless runs and strategy comparison.

Examples
--------
    ghost-commander run --strategy global --seed 7
    ghost-commander run --preset swarm --strategy auction --save run.json
    ghost-commander compare --preset scarce
    ghost-commander presets
"""

from __future__ import annotations

import argparse
import dataclasses
import sys

from .coordination import STRATEGIES
from .sim import (
    PRESETS,
    SWEEP_PARAMS,
    Scenario,
    compare_robust,
    compare_strategies,
    run_scenario,
    sweep,
    verify_run,
)


def _scenario_from_args(args: argparse.Namespace) -> Scenario:
    base = PRESETS.get(args.preset, PRESETS["default"])
    overrides: dict[str, object] = {}
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.agents is not None:
        overrides["n_agents"] = args.agents
    if args.tasks is not None:
        overrides["n_tasks"] = args.tasks
    if args.max_ticks is not None:
        overrides["max_ticks"] = args.max_ticks
    return dataclasses.replace(base, **overrides) if overrides else base


def _cmd_run(args: argparse.Namespace) -> int:
    scenario = _scenario_from_args(args)
    rec = run_scenario(scenario, args.strategy, replan=args.replan)
    m = rec.final_metrics
    print(f"scenario={scenario.name} strategy={args.strategy} seed={scenario.seed}"
          f"{' replan=on' if args.replan else ''}")
    print(f"  ticks recorded : {len(rec.frames) - 1}")
    if scenario.revisit_every > 0:
        h = rec.metrics_history
        cov = sum(s.get("coverage", 1.0) for s in h) / len(h) * 100
        services = sum(1 for e in rec.events if e["type"] == "task.completed")
        print(f"  mean coverage  : {cov:.1f}%   ({services} services, "
              f"{m['tasks_total']} points, revisit={scenario.revisit_every})")
    print(f"  tasks done     : {m['tasks_done']}/{m['tasks_total']}")
    print(f"  tasks failed   : {m.get('tasks_failed', 0)}")
    print(f"  mission (wgt)  : {m['mission_completion'] * 100:.1f}%")
    print(f"  agents lost    : {m['agents_total'] - m['agents_alive']}/{m['agents_total']}")
    print(f"  reassignments  : {m['reassignments']}")
    print(f"  events         : {len(rec.events)}")
    print(f"  digest         : {rec.digest()}")
    if args.save:
        rec.save(args.save)
        print(f"  saved -> {args.save}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    scenario = _scenario_from_args(args)
    metric = "coverage" if scenario.revisit_every > 0 else "mission"
    if args.seeds and args.seeds > 1:
        seeds = [scenario.seed + i for i in range(args.seeds)]
        robust = compare_robust(scenario, seeds, args.strategies, replan=args.replan)
        print(f"scenario={scenario.name} robust over {args.seeds} seeds "
              f"({scenario.seed}..{scenario.seed + args.seeds - 1})  metric={metric}\n")
        header = (f"{'rank':<5}{'strategy':<10}{'mean':<8}{'std':<8}{'min':<8}"
                  f"{'max':<8}{'win-rate':<9}")
        print(header + "\n" + "-" * len(header))
        for i, r in enumerate(robust, start=1):
            print(f"{i:<5}{r.strategy:<10}{r.mean*100:<7.1f} {r.std*100:<7.1f} "
                  f"{r.lo*100:<7.1f} {r.hi*100:<7.1f} {r.win_rate*100:<8.0f}%")
        print(f"\nbest on average: {robust[0].strategy}")
        return 0
    results = compare_strategies(scenario, args.strategies, replan=args.replan)
    print(f"scenario={scenario.name} seed={scenario.seed} "
          f"agents={scenario.n_agents} tasks={scenario.n_tasks}"
          f"{' replan=on' if args.replan else ''}\n")
    if scenario.revisit_every > 0:
        header = f"{'rank':<5}{'strategy':<10}{'coverage':<11}{'lost':<7}{'reassign':<9}"
        print(header + "\n" + "-" * len(header))
        for i, r in enumerate(results, start=1):
            print(f"{i:<5}{r.strategy:<10}{r.mean_coverage*100:<10.1f} "
                  f"{r.agents_lost:<7}{r.reassignments:<9}")
    else:
        header = (f"{'rank':<5}{'strategy':<10}{'mission':<10}{'done':<9}{'failed':<8}"
                  f"{'ticks':<8}{'lost':<7}{'reassign':<9}")
        print(header + "\n" + "-" * len(header))
        for i, r in enumerate(results, start=1):
            ticks = "-" if r.ticks_to_finish is None else str(r.ticks_to_finish)
            print(f"{i:<5}{r.strategy:<10}{r.completion*100:.1f}%   "
                  f"{f'{r.tasks_done}/{r.tasks_total}':<9}{r.tasks_failed:<8}{ticks:<8}"
                  f"{r.agents_lost:<7}{r.reassignments:<9}")
    print(f"\nwinner: {results[0].strategy}")
    return 0


def _cmd_sweep(args: argparse.Namespace) -> int:
    scenario = _scenario_from_args(args)
    names = args.strategies or list(STRATEGIES)
    data = sweep(scenario, args.param, args.values, names, seeds=args.seeds,
                 replan=args.replan)
    metric = "coverage" if scenario.revisit_every > 0 else "mission"
    label = SWEEP_PARAMS[args.param][1]
    print(f"scenario={scenario.name} sweep {args.param} ({label})  metric={metric}"
          f"  seeds={args.seeds}\n")
    header = f"{label:<16}" + "".join(f"{n:<10}" for n in names)
    print(header + "\n" + "-" * len(header))
    for i, v in enumerate(args.values):
        row = f"{v:<16}" + "".join(f"{data[n][i][1] * 100:<10.1f}" for n in names)
        print(row)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    ok, saved, got = verify_run(args.file)
    print(f"file   : {args.file}")
    print(f"saved  : {saved}")
    print(f"re-run : {got}")
    print("RESULT : OK - reproducible (digests match)" if ok
          else "RESULT : MISMATCH - the run did not reproduce")
    return 0 if ok else 1


def _cmd_presets(_: argparse.Namespace) -> int:
    print("presets:")
    for name, sc in PRESETS.items():
        print(f"  {name:<10} agents={sc.n_agents:<4} tasks={sc.n_tasks:<4} "
              f"max_ticks={sc.max_ticks}")
    print(f"\nstrategies: {', '.join(STRATEGIES)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ghost-commander", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--preset", default="default", choices=list(PRESETS))
        sp.add_argument("--seed", type=int, default=None)
        sp.add_argument("--agents", type=int, default=None)
        sp.add_argument("--tasks", type=int, default=None)
        sp.add_argument("--max-ticks", dest="max_ticks", type=int, default=None)
        sp.add_argument("--replan", action="store_true",
                        help="continuous rescue preemption (redirect en-route agents "
                             "to tasks about to expire)")

    run = sub.add_parser("run", help="run one mission")
    add_common(run)
    run.add_argument("--strategy", default="global", choices=list(STRATEGIES))
    run.add_argument("--save", default=None, help="save recording to JSON")
    run.set_defaults(func=_cmd_run)

    cmp = sub.add_parser("compare", help="compare all strategies on one scenario")
    add_common(cmp)
    cmp.add_argument("--strategies", nargs="+", default=None, choices=list(STRATEGIES))
    cmp.add_argument("--seeds", type=int, default=1,
                     help="run over N seeds and report mean/std/win-rate (robustness)")
    cmp.set_defaults(func=_cmd_compare)

    swp = sub.add_parser("sweep", help="vary a parameter and see how strategies scale")
    add_common(swp)
    swp.add_argument("--param", default="agents", choices=list(SWEEP_PARAMS))
    swp.add_argument("--values", type=float, nargs="+", required=True,
                     help="values to sweep, e.g. --values 20 40 60 80 100")
    swp.add_argument("--strategies", nargs="+", default=None, choices=list(STRATEGIES))
    swp.add_argument("--seeds", type=int, default=1,
                     help="average each point over N seeds")
    swp.set_defaults(func=_cmd_sweep)

    vfy = sub.add_parser("verify", help="re-run a saved recording and check its digest")
    vfy.add_argument("file", help="path to a recording JSON (from `run --save`)")
    vfy.set_defaults(func=_cmd_verify)

    pre = sub.add_parser("presets", help="list presets and strategies")
    pre.set_defaults(func=_cmd_presets)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
