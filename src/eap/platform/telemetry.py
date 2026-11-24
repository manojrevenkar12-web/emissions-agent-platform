"""Observability for agents: one span per model call, tool call, check and human step, with tokens, cost and
latency. The same records feed the study's numbers and, in the service, OpenTelemetry spans with GenAI
semantic-convention attributes that a Datadog Agent (or any OTLP collector) receives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class Span:
    name: str
    trace: str
    start_ms: float
    duration_ms: float
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_eur: float = 0.0
    status: str = "ok"
    attrs: dict[str, Any] = field(default_factory=dict)

    def otel_attributes(self) -> dict[str, Any]:
        a: dict[str, Any] = {"eap.trace": self.trace, "eap.status": self.status, **{f"eap.{k}": v for k, v in self.attrs.items()}}
        if self.model:
            a.update({"gen_ai.request.model": self.model, "gen_ai.usage.input_tokens": self.tokens_in, "gen_ai.usage.output_tokens": self.tokens_out, "eap.cost_eur": round(self.cost_eur, 6)})
        return a


@dataclass
class Recorder:
    keep_traces: set[str] = field(default_factory=set)
    traces: dict[str, list[Span]] = field(default_factory=dict)
    _lat: dict[str, list[float]] = field(default_factory=dict)
    _tok: dict[str, list[int]] = field(default_factory=dict)
    cost_eur: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model_calls: dict[str, int] = field(default_factory=dict)
    exporter: Any = None

    def add(self, s: Span) -> Span:
        self._lat.setdefault(s.name, []).append(s.duration_ms)
        self._tok.setdefault(s.name, [0, 0])
        self._tok[s.name][0] += s.tokens_in
        self._tok[s.name][1] += s.tokens_out
        self.cost_eur += s.cost_eur
        self.tokens_in += s.tokens_in
        self.tokens_out += s.tokens_out
        if s.model:
            self.model_calls[s.model] = self.model_calls.get(s.model, 0) + 1
        if s.trace in self.keep_traces:
            self.traces.setdefault(s.trace, []).append(s)
        if self.exporter is not None:
            self.exporter(s)
        return s

    def summary(self) -> dict[str, dict[str, float]]:
        out = {}
        for name, xs in sorted(self._lat.items()):
            a = np.array(xs)
            out[name] = {"count": len(xs), "p50_ms": float(np.percentile(a, 50)), "p95_ms": float(np.percentile(a, 95)), "tokens_in": self._tok[name][0], "tokens_out": self._tok[name][1]}
        return out


def cost(prices: dict[str, dict[str, float]], model: str, tokens_in: int, tokens_out: int) -> float:
    p = prices[model]
    return (tokens_in * p["in"] + tokens_out * p["out"]) / 1e6
