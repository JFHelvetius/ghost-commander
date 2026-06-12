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
from .sim import PRESETS, Scenario, compare_strategies, run_scenario


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
    rec = run_scenario(scenario, args.strategy)
    m = rec.final_metrics
    print(f"scenario={scenario.name} strategy={args.strategy} seed={scenario.seed}")
    print(f"  ticks recorded : {len(rec.frames) - 1}")
    print(f"  tasks done     : {m['tasks_done']}/{m['tasks_total']}")
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
    results = compare_strategies(scenario, args.strategies)
    print(f"scenario={scenario.name} seed={scenario.seed} "
          f"agents={scenario.n_agents} tasks={scenario.n_tasks}\n")
    header = f"{'rank':<5}{'strategy':<10}{'mission':<10}{'done':<9}{'ticks':<8}{'lost':<7}{'reassign':<9}"
    print(header)
    print("-" * len(header))
    for i, r in enumerate(results, start=1):
        ticks = "-" if r.ticks_to_finish is None else str(r.ticks_to_finish)
        mission = f"{r.completion * 100:.1f}%"
        done = f"{r.tasks_done}/{r.tasks_total}"
        print(
            f"{i:<5}{r.strategy:<10}{mission:<10}{done:<9}{ticks:<8}"
            f"{r.agents_lost:<7}{r.reassignments:<9}"
        )
    print(f"\nwinner: {results[0].strategy}")
    return 0


def _cmd_presets(_: argparse.Namespace) -> int:
    print("presets:")
    for name, sc in PRESETS.items():
        print(f"  {name:<10} agents={sc.n_agents:<4} tasks={sc.n_tasks:<4} max_ticks={sc.max_ticks}")
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

    run = sub.add_parser("run", help="run one mission")
    add_common(run)
    run.add_argument("--strategy", default="global", choices=list(STRATEGIES))
    run.add_argument("--save", default=None, help="save recording to JSON")
    run.set_defaults(func=_cmd_run)

    cmp = sub.add_parser("compare", help="compare all strategies on one scenario")
    add_common(cmp)
    cmp.add_argument("--strategies", nargs="+", default=None, choices=list(STRATEGIES))
    cmp.set_defaults(func=_cmd_compare)

    pre = sub.add_parser("presets", help="list presets and strategies")
    pre.set_defaults(func=_cmd_presets)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
