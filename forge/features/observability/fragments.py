"""Observability fragments — logging/tracing instrumentation + health.

``observability`` is the legacy Logfire/OTel-mixed fragment kept for
backward compat; ``observability_otel`` is the canonical OpenTelemetry-
only path. ``enhanced_health`` adds Redis + Keycloak readiness probes
on top of the base ``/health`` endpoint shipped by every backend.
"""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def register_all(api: ForgeAPI) -> None:
    api.add_fragment(
        Fragment(
            name="observability",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("observability", "python"),
                    dependencies=("logfire>=3.0.0",),
                    env_vars=(
                        ("LOGFIRE_TOKEN", ""),
                        ("LOGFIRE_SERVICE_NAME", "forge-service"),
                    ),
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("observability", "node"),
                    dependencies=(
                        "@opentelemetry/sdk-node@0.55.0",
                        "@opentelemetry/auto-instrumentations-node@0.55.0",
                        "@opentelemetry/exporter-trace-otlp-http@0.55.0",
                        "@opentelemetry/resources@1.29.0",
                        "@opentelemetry/semantic-conventions@1.29.0",
                    ),
                    env_vars=(
                        ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                        ("OTEL_SERVICE_NAME", "forge-service"),
                        ("OTEL_SERVICE_VERSION", "0.1.0"),
                    ),
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("observability", "rust"),
                    # opentelemetry-otlp 0.27's ``grpc-tonic`` feature pulls in
                    # tonic 0.12 → tower 0.4.13. tower 0.4 writes
                    # ``IndexMap<K, V>`` in its ready_cache module, relying on
                    # the ``S = RandomState`` default that only exists when
                    # indexmap-1's non-default ``std`` feature is on. With
                    # cargo's resolver=2, no other dep in this graph activates
                    # std, so tower 0.4 fails to compile under ``cargo clippy``.
                    # Force-enable here so the upstream API regression doesn't
                    # surface as a CI failure.
                    dependencies=(
                        "opentelemetry@0.27",
                        'opentelemetry_sdk = { version = "0.27", features = ["rt-tokio"] }',
                        'opentelemetry-otlp = { version = "0.27", features = ["grpc-tonic"] }',
                        "tracing-opentelemetry@0.28",
                        'indexmap = { version = "1", features = ["std"] }',
                    ),
                    env_vars=(
                        ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                        ("OTEL_SERVICE_NAME", "forge-service"),
                    ),
                ),
            },
        )
    )

    api.add_fragment(
        Fragment(
            name="enhanced_health",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("enhanced_health", "python"),
                    dependencies=("redis>=6.0.0",),
                    env_vars=(
                        ("REDIS_URL", "redis://redis:6379/0"),
                        ("KEYCLOAK_HEALTH_URL", "http://keycloak:9000/health/ready"),
                    ),
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("enhanced_health", "node"),
                    dependencies=("redis@4.7.0",),
                    env_vars=(
                        ("REDIS_URL", "redis://redis:6379/0"),
                        ("KEYCLOAK_HEALTH_URL", "http://keycloak:9000/health/ready"),
                    ),
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("enhanced_health", "rust"),
                    env_vars=(
                        ("REDIS_URL", "redis://redis:6379/0"),
                        ("KEYCLOAK_HEALTH_URL", "http://keycloak:9000/health/ready"),
                    ),
                ),
            },
        )
    )

    api.add_fragment(
        Fragment(
            name="error_port",
            # RFC-007 (Pillar E.1) — promotes the hand-written error-handler
            # code already shipping in every base template into a swappable
            # port. Tier 1 from the start: the wire shape is already proven
            # cross-language by the auth SDKs, so a Python-only port would
            # be a downgrade. Plugins shipping custom envelopes implement
            # ``ErrorPort`` and register their adapter in place of
            # ``DefaultErrorPort``.
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("error_port", "python"),
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("error_port", "node"),
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("error_port", "rust"),
                    # The port + default adapter use serde + serde_json +
                    # thiserror in their type declarations and the
                    # ``DefaultErrorPort`` body. Listed so the fragment can
                    # land on a project that doesn't already depend on
                    # them; cargo de-dupes when other fragments overlap.
                    dependencies=(
                        'serde = { version = "1", features = ["derive"] }',
                        'serde_json = "1"',
                        'thiserror = "1"',
                    ),
                ),
            },
        )
    )

    api.add_fragment(
        Fragment(
            name="observability_otel",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("observability_otel", "python"),
                    dependencies=(
                        "opentelemetry-api>=1.28.0",
                        "opentelemetry-sdk>=1.28.0",
                        "opentelemetry-exporter-otlp-proto-grpc>=1.28.0",
                        "opentelemetry-instrumentation-fastapi>=0.49b0",
                        "opentelemetry-instrumentation-httpx>=0.49b0",
                    ),
                    env_vars=(
                        ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                        ("OTEL_SERVICE_NAME", ""),
                        ("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=dev"),
                    ),
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("observability_otel", "node"),
                    dependencies=(
                        "@opentelemetry/sdk-node@^0.55.0",
                        "@opentelemetry/resources@^1.28.0",
                        "@opentelemetry/exporter-trace-otlp-grpc@^0.55.0",
                        "@opentelemetry/auto-instrumentations-node@^0.51.0",
                    ),
                    env_vars=(
                        ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                        ("OTEL_SERVICE_NAME", ""),
                    ),
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("observability_otel", "rust"),
                    # See the ``observability`` fragment above for why indexmap
                    # is force-enabled — same tower 0.4 ready_cache transitive.
                    dependencies=(
                        "opentelemetry@0.27",
                        "opentelemetry_sdk@0.27",
                        "opentelemetry-otlp@0.27",
                        "tracing-opentelemetry@0.28",
                        'indexmap = { version = "1", features = ["std"] }',
                    ),
                    env_vars=(
                        ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                        ("OTEL_SERVICE_NAME", ""),
                    ),
                ),
            },
        )
    )

    api.add_fragment(
        Fragment(
            name="observability_metrics_middleware",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("metrics_middleware", "python"),
                    dependencies=(
                        "opentelemetry-api>=1.20.0",
                    ),
                ),
            },
        )
    )
