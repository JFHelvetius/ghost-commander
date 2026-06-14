"""Market / auction-based assignment.

Each open slot is auctioned; every available agent bids
``priority_weight / (distance + eps)`` and the highest bidder wins one slot.
Unlike greedy (which is agent-centric and first-come-first-served), the auction
is task-centric and resolves contention globally per round, so a slightly closer
agent does not monopolize a task another agent wanted more. Deterministic ties
broken by agent id, then task id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Assignment, can_fill, fill_slot, priority_weight

if TYPE_CHECKING:
    from ghost_commander.domain import World

_EPS = 1e-6


class AuctionStrategy:
    name = "auction"

    def assign(self, world: World) -> list[Assignment]:
        assignments: list[Assignment] = []
        available = {a.id: a for a in world.available_agents()}
        tasks = {t.id: t for t in world.assignable_tasks()}
        needs = {tid: world.needed_slots(t) for tid, t in tasks.items()}

        # Round-based: each round, every open slot picks its best remaining bidder.
        while available and any(needs.values()):
            round_claims: list[tuple[float, int, int]] = []  # (bid, agent_id, task_id)
            for task_id, task in tasks.items():
                if not needs[task_id]:
                    continue
                best: tuple[float, int] | None = None  # (bid, agent_id)
                for agent in available.values():
                    if not can_fill(needs[task_id], agent):
                        continue
                    bid = priority_weight(task.priority_at(world.tick)) / (
                        agent.distance_to(task.x, task.y) + _EPS
                    )
                    if best is None or bid > best[0] or (bid == best[0] and agent.id < best[1]):
                        best = (bid, agent.id)
                if best is not None:
                    round_claims.append((best[0], best[1], task_id))

            if not round_claims:
                break

            # Resolve: highest bid overall wins; an agent can only win once per round.
            round_claims.sort(key=lambda c: (-c[0], c[1], c[2]))
            taken_agents: set[int] = set()
            progressed = False
            for _bid, agent_id, task_id in round_claims:
                if agent_id in taken_agents or agent_id not in available or not needs[task_id]:
                    continue
                if not fill_slot(needs[task_id], available[agent_id]):
                    continue
                assignments.append((agent_id, task_id))
                taken_agents.add(agent_id)
                del available[agent_id]
                progressed = True
            if not progressed:
                break
        return assignments


__all__ = ["AuctionStrategy"]
