"""Deterministic fixed-step simulation clock.

A deliberately small relative of Project Ghost's ``core.clock.SimClockImpl``.
Ghost's clock is a full min-heap event scheduler because a drone control loop
multiplexes callbacks at different rates. Ghost Commander's simulation is a flat
fixed-step tick loop, so we keep only what we need: integer-nanosecond time with
no float accumulation, advanced exclusively by ``tick()`` (no wall clock). The
determinism contract is identical — same step, same number of ticks, same time.
"""

from __future__ import annotations

from typing import Final

_DEFAULT_STEP_NS: Final[int] = 100_000_000  # 100 ms per tick (10 Hz)


class SimClock:
    """Fixed-step deterministic clock. Time only moves via ``tick()``."""

    def __init__(self, step_ns: int = _DEFAULT_STEP_NS) -> None:
        if step_ns <= 0:
            raise ValueError(f"step_ns must be > 0; got {step_ns}")
        self._step_ns: Final[int] = step_ns
        self._tick: int = 0

    @property
    def tick(self) -> int:
        return self._tick

    @property
    def step_ns(self) -> int:
        return self._step_ns

    def now_ns(self) -> int:
        return self._tick * self._step_ns

    def now_s(self) -> float:
        return self.now_ns() / 1e9

    def advance(self) -> int:
        self._tick += 1
        return self._tick


__all__ = ["SimClock"]
