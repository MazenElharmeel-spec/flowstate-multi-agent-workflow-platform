"""Optional OpenTelemetry tracing setup and shared tracer."""

from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from backend.app.core.config import get_settings

settings = get_settings()
tracer = trace.get_tracer("agent-workflow-platform")
_initialized = False


def setup_tracing(app: Any | None = None) -> None:
    """Configure shared spans and instrument FastAPI when an app is supplied."""
    global _initialized
    if not _initialized:
        provider = TracerProvider(
            resource=Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
        )
        if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
            exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _initialized = True
    if app is not None:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=trace.get_tracer_provider())
