"""Quality monitoring in production: a Bernoulli CUSUM on first reads that fail the code checks.

A provider can change a model under the same name. Each first read is one observation (failed checks or
not). After a baseline, the statistic adds the log-likelihood ratio of "failure rate rose by delta" against
the baseline rate; past `h` it raises an alarm and the router sends first reads to the escalation model for
`pin_days`. The monitor reads only what the platform sees (check outcomes), never the truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Cusum:
    delta: float
    h: float
    baseline_obs: int
    pin_days: int
    s: float = 0.0
    n: int = 0
    fails: int = 0
    p0: float | None = None
    alarms: list[int] = field(default_factory=list)
    pinned_until: int = -1
    series: list[dict[str, float]] = field(default_factory=list)
    _day: int = -1
    _day_n: int = 0
    _day_f: int = 0

    @classmethod
    def from_cfg(cls, cfg: dict[str, Any]) -> Cusum:
        m = cfg["monitor"]
        return cls(float(m["delta"]), float(m["h"]), int(m["baseline_obs"]), int(m["pin_days"]))

    def _flush(self) -> None:
        if self._day >= 0 and self._day_n:
            self.series.append({"day": self._day, "rate": self._day_f / self._day_n, "s": round(self.s, 3), "n": self._day_n})
        self._day_n = self._day_f = 0

    def observe(self, day: int, failed: bool) -> None:
        if day != self._day:
            self._flush()
            self._day = day
        self._day_n += 1
        self._day_f += int(failed)
        self.n += 1
        self.fails += int(failed)
        if self.n <= self.baseline_obs:
            self.p0 = (self.fails + 1) / (self.n + 2)
            return
        p0 = min(max(self.p0 or 0.5, 0.02), 0.95)
        p1 = min(p0 + self.delta, 0.99)
        inc = math.log(p1 / p0) if failed else math.log((1 - p1) / (1 - p0))
        self.s = max(0.0, self.s + inc)
        if self.s > self.h:
            self.alarms.append(day)
            self.pinned_until = day + self.pin_days
            self.s = 0.0

    def close_through(self, day: int) -> None:
        self._flush()
        self._day = day

    def pinned(self, day: int) -> bool:
        return day <= self.pinned_until
