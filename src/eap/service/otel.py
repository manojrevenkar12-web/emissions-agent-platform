"""OpenTelemetry for the service: every platform span becomes an OTel span with GenAI attributes.

With OTEL_EXPORTER_OTLP_ENDPOINT set (a Datadog Agent with OTLP intake, or any collector), spans leave over
OTLP/HTTP; otherwise they stay in memory, which the tests read.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ..platform.telemetry import Span


def setup(service: str = "emissions-agent-platform") -> tuple[Callable[[Span], None], InMemorySpanExporter | None]:
    provider = TracerProvider(resource=Resource.create({"service.name": service, "deployment.environment": os.environ.get("EAP_ENV", "local")}))
    memory: InMemorySpanExporter | None = None
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        memory = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(memory))
    tracer = provider.get_tracer("eap")

    def export(s: Span) -> None:
        end = time.time_ns()
        start = end - int(s.duration_ms * 1e6)
        span = tracer.start_span(s.name, start_time=start, attributes=s.otel_attributes())
        if s.status not in ("ok",) and not s.status.startswith("retried"):
            span.set_status(trace.Status(trace.StatusCode.ERROR, s.status))
        span.end(end_time=end)

    return export, memory
