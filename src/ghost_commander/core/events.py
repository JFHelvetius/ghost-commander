"""Synchronous in-process event bus + typed event catalog.

Adapted from Project Ghost's ``events.bus`` / ``events.types`` (Apache-2.0).
Ghost built this to get an ordered, monotonically-sequenced, severity-filtered
record of everything that happens in a run. Ghost Commander needs precisely the
same thing to drive the **event timeline** in the dashboard, so we reuse the
design: ``publish`` stamps a global monotonic ``sequence`` and dispatches
synchronously; a subscriber raising never breaks the others.

The ``EventType`` catalog here is Commander-specific (assignment / failure /
mission lifecycle) rather than Ghost's drone-safety catalog.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


class EventSeverity(IntEnum):
    DEBUG = 10
    INFO = 20
    WARN = 30
    ERROR = 40
    CRITICAL = 50


class EventType(StrEnum):
    # lifecycle
    SIM_START = "sim.start"
    SIM_END = "sim.end"
    STEP = "sim.step"
    # tasks
    TASK_CREATED = "task.created"
    TASK_DETECTED = "task.detected"
    TASK_ASSIGNED = "task.assigned"
    TASK_REASSIGNED = "task.reassigned"
    TASK_PROGRESS = "task.progress"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    # agents
    AGENT_RESOURCE_LOW = "agent.resource_low"
    AGENT_RECHARGING = "agent.recharging"
    AGENT_FAILED = "agent.failed"
    AGENT_RECOVERED = "agent.recovered"
    # mission
    MISSION_COMPLETE = "mission.complete"
    MISSION_DEGRADED = "mission.degraded"


@dataclass(frozen=True)
class Event:
    """A single timeline event. ``sequence`` is assigned by the bus on publish."""

    type: EventType
    severity: EventSeverity
    source: str
    sim_tick: int
    sequence: int = 0
    payload: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        """Flatten for tabular display (dashboard timeline)."""
        row = {
            "seq": self.sequence,
            "tick": self.sim_tick,
            "type": str(self.type),
            "severity": self.severity.name,
            "source": self.source,
        }
        row.update({f"p_{k}": v for k, v in self.payload.items()})
        return row


@dataclass
class _SubscriberEntry:
    callback: Callable[[Event], None]
    min_severity: EventSeverity
    types: tuple[EventType, ...] | None
    unsubscribed: bool = False


@dataclass(frozen=True)
class Subscription:
    unsubscribe: Callable[[], None]


class EventBus:
    """Synchronous in-process event bus. ``publish`` stamps a monotonic sequence."""

    def __init__(self) -> None:
        self._subscribers: list[_SubscriberEntry] = []
        self._next_seq: int = 0

    def publish(self, ev: Event) -> Event:
        seq = self._next_seq
        self._next_seq += 1
        sealed = dataclasses.replace(ev, sequence=seq)
        for entry in list(self._subscribers):
            if entry.unsubscribed:
                continue
            if sealed.severity < entry.min_severity:
                continue
            if entry.types is not None and sealed.type not in entry.types:
                continue
            try:
                entry.callback(sealed)
            except Exception:  # subscriber isolation, exactly like Ghost
                pass
        return sealed

    def emit(
        self,
        type: EventType,
        source: str,
        sim_tick: int,
        severity: EventSeverity = EventSeverity.INFO,
        **payload: Any,
    ) -> Event:
        """Convenience constructor + publish."""
        return self.publish(
            Event(
                type=type,
                severity=severity,
                source=source,
                sim_tick=sim_tick,
                payload=payload,
            )
        )

    def subscribe(
        self,
        types: Iterable[EventType],
        cb: Callable[[Event], None],
        min_severity: EventSeverity = EventSeverity.DEBUG,
    ) -> Subscription:
        types_tuple = tuple(types)
        if not types_tuple:
            raise ValueError("subscribe: types cannot be empty; use subscribe_all().")
        return self._register(_SubscriberEntry(cb, min_severity, types_tuple))

    def subscribe_all(
        self,
        cb: Callable[[Event], None],
        min_severity: EventSeverity = EventSeverity.DEBUG,
    ) -> Subscription:
        return self._register(_SubscriberEntry(cb, min_severity, None))

    def _register(self, entry: _SubscriberEntry) -> Subscription:
        self._subscribers.append(entry)

        def _unsubscribe() -> None:
            entry.unsubscribed = True

        return Subscription(unsubscribe=_unsubscribe)


class EventLog:
    """A subscriber that simply records every event. Powers the timeline view."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def attach(self, bus: EventBus, min_severity: EventSeverity = EventSeverity.DEBUG) -> None:
        bus.subscribe_all(self.events.append, min_severity=min_severity)


__all__ = [
    "Event",
    "EventBus",
    "EventLog",
    "EventSeverity",
    "EventType",
    "Subscription",
]
