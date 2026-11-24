"""Every coin the world flips, keyed by (seed, variant, purpose, id...).

A draw depends only on its key, never on the order designs ask for it, so two designs that make the same
call get the same answer and a difference between designs comes from the design. Draws are memoised per
seed, so the record of what was drawn can be compared across designs (tests/test_same_luck.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..rng import keyed


@dataclass
class Luck:
    seed: int
    variant: str
    _u: dict[tuple[object, ...], np.ndarray] = field(default_factory=dict)

    def draws(self, *key: object, n: int = 2) -> np.ndarray:
        """n uniforms followed by n standard normals for this key."""
        k = (n, *key)
        hit = self._u.get(k)
        if hit is None:
            rng = keyed(self.seed, self.variant, *key)
            hit = np.concatenate([rng.random(n), rng.normal(size=n)])
            self._u[k] = hit
        return hit

    def u(self, *key: object) -> float:
        return float(self.draws(*key, n=1)[0])

    def uz(self, *key: object) -> tuple[float, float]:
        d = self.draws(*key, n=1)
        return float(d[0]), float(d[1])

    def rows(self, n_rows: int, *key: object) -> np.ndarray:
        k = ("rows", n_rows, *key)
        hit = self._u.get(k)
        if hit is None:
            hit = keyed(self.seed, self.variant, "rows", *key).random(n_rows)
            self._u[k] = hit
        return hit

    def record(self) -> dict[tuple[object, ...], np.ndarray]:
        return dict(self._u)


def sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-x)))


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return float(np.log(p / (1 - p)))
