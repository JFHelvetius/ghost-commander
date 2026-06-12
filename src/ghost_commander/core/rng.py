"""Hierarchical deterministic random source.

Adapted from Project Ghost's ``core.clock.random_source`` (Apache-2.0).
Reused verbatim in spirit because reproducible failures are the whole point
of Ghost Commander: *the same seed + the same scenario + the same strategy
must produce the same mission, bit for bit*. That is exactly the guarantee
Ghost's ``RandomSource`` was built to provide, so we vendor the design here
rather than reinvent it.

Derivation model:

- Root: ``RandomSource(seed=S, label="/")``.
- ``root.child("failures")`` derives a child whose seed is
  ``SHA-256(f"{S:x}:failures")[:8]`` and whose label is ``/failures``.
- Distinct ``.child(...)`` chains that happen to share a final path do NOT
  necessarily produce the same streams. The invariant is: **same call tree +
  same root seed -> same numbers.**

SHA-256 is stable across CPython versions (unaffected by ``PYTHONHASHSEED``),
so runs reproduce across machines.
"""

from __future__ import annotations

import hashlib
from typing import Final

import numpy as np

_SEED_BYTES: Final[int] = 8
_MAX_SEED: Final[int] = 2**63 - 1


def _derive_child_seed(parent_seed: int, child_label: str) -> int:
    payload = f"{parent_seed:x}:{child_label}".encode()
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:_SEED_BYTES], "big") & _MAX_SEED


class RandomSource:
    """Concrete hierarchical random source backed by ``numpy.random.Generator``."""

    seed: int
    label: str

    def __init__(self, seed: int, label: str = "/") -> None:
        if seed < 0:
            raise ValueError(f"seed must be >= 0; got {seed}")
        if not label.startswith("/"):
            raise ValueError(f"label must start with '/'; got {label!r}")
        self.seed = seed
        self.label = label
        self._rng: np.random.Generator = np.random.default_rng(seed)

    def child(self, label: str) -> RandomSource:
        """Derive a sub-source with a seed deterministically derived from ``label``."""
        if not label:
            raise ValueError("child label cannot be empty")
        segment = label.lstrip("/")
        if not segment:
            raise ValueError(f"child label must contain more than slashes; got {label!r}")
        child_seed = _derive_child_seed(self.seed, segment)
        sep = "" if self.label.endswith("/") else "/"
        return RandomSource(seed=child_seed, label=self.label + sep + segment)

    def uniform(self, a: float, b: float) -> float:
        return float(self._rng.uniform(a, b))

    def normal(self, mu: float, sigma: float) -> float:
        return float(self._rng.normal(mu, sigma))

    def integers(self, low: int, high: int) -> int:
        return int(self._rng.integers(low, high))

    def chance(self, p: float) -> bool:
        """Return ``True`` with probability ``p`` (Bernoulli draw)."""
        return bool(self._rng.random() < p)

    def numpy_rng(self) -> np.random.Generator:
        """Return the wrapped generator. Successive calls return the *same* object;
        create a ``child()`` for independent concerns."""
        return self._rng


__all__ = ["RandomSource"]
