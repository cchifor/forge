//! OpenTelemetry OTLP export for Axum/Rust backends.
//!
//! [`otel_layer`] builds a `tracing` layer that exports spans to an OTLP
//! collector over HTTP/protobuf when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
//! It returns `None` when the endpoint is unset (or the exporter fails to
//! build), so the service runs fine without a collector — spans simply stay
//! local. `main.rs` pushes the returned layer onto its tracing layer set.
//!
//! Env vars:
//!   * `OTEL_EXPORTER_OTLP_ENDPOINT` — OTLP/HTTP endpoint (e.g.
//!     `http://alloy:4318`). Unset ⇒ no export.
//!   * `OTEL_SERVICE_NAME` — resource service name (defaulted by `main.rs`).

use opentelemetry::KeyValue;
use opentelemetry::trace::TracerProvider as _;
use opentelemetry_otlp::{SpanExporter, WithExportConfig};
use opentelemetry_sdk::Resource;
use opentelemetry_sdk::runtime;
use opentelemetry_sdk::trace::TracerProvider as SdkTracerProvider;
use tracing_subscriber::Layer;
use tracing_subscriber::registry::Registry;

/// Build the OTLP tracing layer, or `None` when no endpoint is configured.
pub fn otel_layer(service_name: &str) -> Option<Box<dyn Layer<Registry> + Send + Sync>> {
    let endpoint = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT").ok()?;
    if endpoint.trim().is_empty() {
        return None;
    }

    let exporter = SpanExporter::builder()
        .with_http()
        .with_endpoint(endpoint)
        .build()
        .ok()?;

    let provider = SdkTracerProvider::builder()
        .with_batch_exporter(exporter, runtime::Tokio)
        .with_resource(Resource::new(vec![KeyValue::new(
            "service.name",
            service_name.to_string(),
        )]))
        .build();

    let tracer = provider.tracer("forge");
    // Set the global provider so manually-created spans and downstream
    // libraries share the same exporter; the global keeps it alive for the
    // process lifetime.
    let _ = opentelemetry::global::set_tracer_provider(provider);

    Some(tracing_opentelemetry::layer().with_tracer(tracer).boxed())
}
