"""Run recording for replay and post-hoc analysis.

Stores one frame per tick (world snapshot + metrics) plus the full event log.
Because the simulation is fully deterministic, a recording is a faithful,
re-playable transcript: scrubbing the dashboard timeline reads frames, and
re-running the same scenario+seed+strategy reproduces them byte-for-byte
(verified by ``RunRecording.digest``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ghost_commander.core import Event
    from ghost_commander.domain import World

    from .metrics import MetricsSnapshot
    from .scenario import Scenario


@dataclass
class RunRecording:
    scenario_name: str
    strategy: str
    seed: int
    # Each frame is a plain dict {"tick", "world", "metrics"} so it serializes,
    # replays and indexes the same way everywhere (dashboard, tests, JSON).
    frames: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    metrics_history: list[dict[str, float | int]] = field(default_factory=list)

    def add_frame(self, tick: int, world: World, metrics: MetricsSnapshot) -> None:
        self.frames.append(
            {"tick": tick, "world": world.snapshot(), "metrics": metrics.as_dict()}
        )
        self.metrics_history.append(metrics.as_dict())

    def add_event(self, event: Event) -> None:
        self.events.append(event.as_row())

    @property
    def final_metrics(self) -> dict[str, float | int]:
        return self.metrics_history[-1] if self.metrics_history else {}

    def digest(self) -> str:
        """Stable hash of the metrics trajectory — the determinism fingerprint."""
        blob = json.dumps(self.metrics_history, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    # ---------------------------------------------------------- persistence
    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "strategy": self.strategy,
            "seed": self.seed,
            "digest": self.digest(),
            "frames": self.frames,
            "events": self.events,
            "metrics_history": self.metrics_history,
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh)

    @classmethod
    def from_scenario(cls, scenario: Scenario, strategy: str) -> RunRecording:
        return cls(scenario_name=scenario.name, strategy=strategy, seed=scenario.seed)


__all__ = ["RunRecording"]
