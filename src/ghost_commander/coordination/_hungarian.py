"""Hungarian algorithm (Kuhn–Munkres) for square min-cost assignment.

Pure Python, O(n^3), no SciPy dependency. Used by the ``optimal`` strategy to
solve the per-tick assignment exactly, as a baseline against the heuristics.

``solve(cost)`` takes an ``n x n`` matrix of finite floats and returns
``row_to_col``: a list where ``row_to_col[i]`` is the column assigned to row ``i``
(a permutation), minimizing the total cost.
"""

from __future__ import annotations

_INF = float("inf")


def solve(cost: list[list[float]]) -> list[int]:
    n = len(cost)
    if n == 0:
        return []
    # 1-indexed potentials/matching (classic e-maxx formulation).
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)  # p[j] = row matched to column j
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [_INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = _INF
            j1 = -1
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    row_to_col = [-1] * n
    for j in range(1, n + 1):
        if p[j] > 0:
            row_to_col[p[j] - 1] = j - 1
    return row_to_col


__all__ = ["solve"]
