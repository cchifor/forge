"""The generated service must actually EXPORT OpenTelemetry metrics.

``metrics_middleware`` creates its meter at import time
(``metrics.get_meter("http.server")`` -> a proxy counter/histogram). Without a
MeterProvider installed anywhere those instruments forward to the API's default
no-op and nothing is ever exported, even with ``OTEL_EXPORTER_OTLP_ENDPOINT``
set. ``configure_otel`` (the canonical OTel export fragment, which already owns
the TracerProvider) must therefore also install a MeterProvider + OTLP metric
reader so the proxy instruments upgrade to a real meter at startup.

This is a structural guard on the shipped template; the proxy-upgrade behaviour
itself is a documented OTel invariant (an import-time proxy instrument starts
recording once ``set_meter_provider`` runs).
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY


def _otel_source() -> str:
    frag = FRAGMENT_REGISTRY["observability_otel"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    path = (
        Path(impl.fragment_dir)
        / "files"
        / "src"
        / "app"
        / "core"
        / "otel.py"
    )
    return path.read_text(encoding="utf-8")


def test_configure_otel_installs_a_meter_provider() -> None:
    src = _otel_source()
    assert "MeterProvider" in src and "set_meter_provider" in src, (
        "configure_otel must install a MeterProvider so the metrics middleware's "
        "meter is backed (otherwise metrics record into the no-op provider)"
    )
    assert "PeriodicExportingMetricReader" in src, (
        "metrics need a periodic OTLP metric reader to be exported"
    )
    assert "metric_exporter" in src, (
        "must wire an OTLP metric exporter (opentelemetry...metric_exporter)"
    )


def test_otel_metric_exporter_passes_endpoint_bare_for_grpc() -> None:
    """The gRPC OTLP exporter infers the metrics path from the endpoint; the
    ``/v1/metrics`` suffix is the HTTP convention and breaks gRPC. The metric
    exporter must pass the endpoint bare, matching the span exporter in the
    same module."""
    src = _otel_source()
    assert "/v1/metrics" not in src, (
        "gRPC OTLP metric exporter must not append /v1/metrics to the endpoint"
    )


def _metrics_source() -> str:
    frag = FRAGMENT_REGISTRY["observability_metrics_middleware"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    path = Path(impl.fragment_dir) / "files" / "src" / "app" / "middleware" / "metrics.py"
    return path.read_text(encoding="utf-8")


def test_metrics_middleware_hardening() -> None:
    """RED metrics must survive errors, skip operational paths, and track
    in-flight requests (ported behaviours from platform's weld-observability)."""
    src = _metrics_source()
    # Operational endpoints are excluded.
    assert "SKIP_PATHS" in src and "/health" in src and "/metrics" in src
    # In-flight gauge (up-down counter) is incremented/decremented with the
    # SAME status-free attrs (else the +1/-1 never cancel) — count/duration
    # carry the status separately.
    assert "create_up_down_counter" in src and "active_requests" in src
    assert "base_attrs" in src and "req_attrs" in src
    assert "_active_requests.add(1, base_attrs)" in src
    assert "_active_requests.add(-1, base_attrs)" in src
    # An unhandled exception still records the request (status defaults to 500),
    # and count / duration / active-request decrement all run in a finally.
    assert "status_code = 500" in src
    assert "finally:" in src


def test_metrics_middleware_requires_otel_fragment() -> None:
    """The MeterProvider lives in observability_otel's configure_otel. The
    metrics middleware only records into the meter, so selecting it without
    observability_otel would install no provider and silently export nothing.
    Enforce the dependency so the resolver always pulls otel in."""
    frag = FRAGMENT_REGISTRY["observability_metrics_middleware"]
    assert "observability_otel" in frag.depends_on, (
        "observability_metrics_middleware must depend on observability_otel so "
        "a MeterProvider is always installed when metrics are enabled"
    )
