"""Failure model: resource drain, random loss, and coordinated shocks.

Everything stochastic in a mission flows through here, drawing from a dedicated
``failures`` child of the root ``RandomSource``. Keeping failures on their own
stream means changing the layout seed does not perturb the failure sequence and
vice-versa — the kind of separability Project Ghost insists on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ghost_commander.domain import AgentStatus

if TYPE_CHECKING:
    from ghost_commander.core import RandomSource
    from ghost_commander.domain import Agent, World

    from .scenario import Scenario


@dataclass
class FailureOutcome:
    """What happened to one agent this tick (for event emission)."""

    agent_id: int
    kind: str  # "drain" | "depleted" | "random" | "shock"
    resources_before: float
    resources_after: float


class FailureModel:
    def __init__(self, scenario: Scenario, root: RandomSource) -> None:
        self._sc = scenario
        self._rng = root.child("failures")

    def apply(self, world: World, tick: int) -> list[FailureOutcome]:
        """Drain resources and roll for losses. Returns the agents that *died*."""
        sc = self._sc
        deaths: list[FailureOutcome] = []
        shock = sc.shock_tick is not None and tick == sc.shock_tick

        for agent in world.alive_agents():
            before = agent.resources

            # 1) resource drain by activity
            if agent.status is AgentStatus.WORKING:
                agent.resources -= sc.resource_drain_working
            elif agent.status is AgentStatus.MOVING:
                agent.resources -= sc.resource_drain_moving

            # 2) coordinated shock wave (correlated failures)
            if shock and self._rng.chance(sc.shock_failure_rate):
                self._kill(agent, tick)
                deaths.append(FailureOutcome(agent.id, "shock", before, agent.resources))
                continue

            # 3) independent random hard failure
            if self._rng.chance(sc.random_failure_rate):
                self._kill(agent, tick)
                deaths.append(FailureOutcome(agent.id, "random", before, agent.resources))
                continue

            # 4) resource depletion
            if agent.resources <= 0.0:
                agent.resources = 0.0
                self._kill(agent, tick)
                deaths.append(FailureOutcome(agent.id, "depleted", before, 0.0))

        return deaths

    @staticmethod
    def _kill(agent: Agent, tick: int) -> None:
        agent.status = AgentStatus.FAILED
        agent.failed_tick = tick


__all__ = ["FailureModel", "FailureOutcome"]
