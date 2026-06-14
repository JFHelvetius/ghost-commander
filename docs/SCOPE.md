# Scope and boundary

*Canonical statement of what Ghost Commander is for, and the hard line it will
not cross. This document is the reference the README and the codebase point to.*

## What this is

Ghost Commander is an **abstract multi-agent task-allocation simulator**: it
decides **which unit goes to which point** and reorganizes that assignment in
real time as the world changes (failures, shocks, deadlines, arrivals, scarce
specialists, recharge logistics). Every "task" is a generic job at a location
with a priority; an "agent" is a unit that travels and works. There is no notion
of weapons, of human beings as objects, or of force.

## In scope (built, and welcome)

Any situation that maps to *N units serving M points* — civilian or dual-use,
including military **coordination and logistics**:

- **ISR / reconnaissance** — observing/covering points of interest in time.
- **Logistics / resupply** — delivery and sustainment under attrition.
- **Search and rescue / MEDEVAC** — reaching survivors against the clock.
- **Persistent surveillance / area coverage**, route planning, sensor tasking,
  swarm coordination, operating under jamming/EW.
- The coordination science itself: assignment strategies, dynamic
  re-planning, deadlines, specialization, cooperation, recovery.

All of the above stop at **"get the right unit to the right place."**

## Out of scope — the hard boundary

Ghost Commander will **not** model, recommend, simulate, or optimize:

- **Weapon / effector target selection** — choosing *what* to engage.
- **Fire or effector allocation** — assigning a weapon/munition to a target.
- **Lethal-engagement decisions or recommendations**, kill-chain logic.
- **Threat scoring for the purpose of engagement.**

In short: the system's output is *where a unit should go and what job to do* —
never *what to apply force to*.

## Why this boundary is where it is

1. **It is judged by function, not by label.** A "target prioritization module"
   that ranks what to engage is weapon target selection regardless of what it is
   called. Re-framing does not move the line; the capability does.
2. **The targeting algorithm is itself the dangerous artifact.** A *simulation*
   of weapon target selection is still the selection engine. Because here a
   "task" is already a point on a map with a priority, the distance from "task"
   to "target" and from "work" to "engage" is a one-line rename — which is
   exactly why the boundary sits before it, not after.
3. **It aligns with meaningful human control over the use of force**, the line
   the serious international debate on autonomous weapons draws.

## How the boundary is enforced

- The domain model (`Agent`, `Task`, `World`) has **no concept** of weapons,
  munitions, engagement, or human targets. Tasks are abstract work.
- A test, [`tests/test_scope_boundary.py`](../tests/test_scope_boundary.py),
  scans the source's **identifiers** and fails the build if weaponization
  concepts are introduced. The boundary is executable, not just prose.
- Military-flavoured presets (`recon`, `resupply`, …) are framed as
  coordination/logistics and carry this note inline.

This is a deliberate, documented limit. It makes the project *more* credible for
a defense or dual-use audience, not less: Ghost Commander coordinates, sustains,
and observes — it does not decide the use of force.
