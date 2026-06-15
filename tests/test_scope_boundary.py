"""Executable scope boundary (see docs/SCOPE.md).

Ghost Commander coordinates units and tasks; it must never grow weapon
target-selection / lethal-engagement machinery. This test scans the source's
*identifiers* (not comments or strings, so the responsible-use notes that
mention these words in the negative don't trip it) and fails the build if a
weaponization concept is introduced as code.
"""

from __future__ import annotations

import tokenize
from pathlib import Path

# Concepts that must not appear as code identifiers. Deliberately the
# unambiguous weaponization vocabulary — not navigation words like "target"
# (an agent's destination) which the engine legitimately uses in comments.
_FORBIDDEN = (
    "weapon", "munition", "warhead", "missile", "ordnance", "lethal",
    "firecontrol", "fire_control", "killchain", "kill_chain",
    "targeting", "target_selection", "engage", "strike", "threat_score",
)

_SRC = Path(__file__).resolve().parent.parent / "src"


def _identifiers(path: Path) -> set[str]:
    names: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        try:
            for tok in tokenize.generate_tokens(fh.readline):
                if tok.type == tokenize.NAME:
                    names.add(tok.string.lower())
        except tokenize.TokenError:
            pass
    return names


def test_no_weaponization_identifiers_in_source() -> None:
    offenders: list[str] = []
    for py in _SRC.rglob("*.py"):
        for name in _identifiers(py):
            if any(term in name for term in _FORBIDDEN):
                offenders.append(f"{py.relative_to(_SRC)} :: {name}")
    assert not offenders, (
        "Scope boundary violated (see docs/SCOPE.md): weaponization concepts "
        f"appeared as code identifiers: {offenders}"
    )
