"""Observability fragments — logging/tracing instrumentation + health.

``observability`` is the legacy Logfire/OTel-mixed fragment kept for
backward compat; ``observability_otel`` is the canonical OpenTelemetry-
only path. ``enhanced_health`` adds Redis + Keycloak readiness probes
on top of the base ``/health`` endpoint shipped by every backend.
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

register_fragment(
    Fragment(
        name="observability",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="observability/python",
                dependencies=("logfire>=3.0.0",),
                env_vars=(
                    ("LOGFIRE_TOKEN", ""),
                    ("LOGFIRE_SERVICE_NAME", "forge-service"),
                ),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="observability/node",
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
                fragment_dir="observability/rust",
                dependencies=(
                    "opentelemetry@0.27",
                    'opentelemetry_sdk = { version = "0.27", features = ["rt-tokio"] }',
                    'opentelemetry-otlp = { version = "0.27", features = ["grpc-tonic"] }',
                    "tracing-opentelemetry@0.28",
                ),
                env_vars=(
                    ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                    ("OTEL_SERVICE_NAME", "forge-service"),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="enhanced_health",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="enhanced_health/python",
                dependencies=("redis>=6.0.0",),
                env_vars=(
                    ("REDIS_URL", "redis://redis:6379/0"),
                    ("KEYCLOAK_HEALTH_URL", "http://keycloak:9000/health/ready"),
                ),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="enhanced_health/node",
                dependencies=("redis@4.7.0",),
                env_vars=(
                    ("REDIS_URL", "redis://redis:6379/0"),
                    ("KEYCLOAK_HEALTH_URL", "http://keycloak:9000/health/ready"),
                ),
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="enhanced_health/rust",
                env_vars=(
                    ("REDIS_URL", "redis://redis:6379/0"),
                    ("KEYCLOAK_HEALTH_URL", "http://keycloak:9000/health/ready"),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="observability_otel",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="observability_otel/python",
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
                fragment_dir="observability_otel/node",
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
                fragment_dir="observability_otel/rust",
                dependencies=(
                    "opentelemetry@0.27",
                    "opentelemetry_sdk@0.27",
                    "opentelemetry-otlp@0.27",
                    "tracing-opentelemetry@0.28",
                ),
                env_vars=(
                    ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                    ("OTEL_SERVICE_NAME", ""),
                ),
            ),
        },
    )
)
