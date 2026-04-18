//! OpenTelemetry layer for tracing_subscriber.
//!
//! Builds a `tracing_opentelemetry::Layer` backed by an OTLP gRPC exporter
//! when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Otherwise returns `None` and
//! the service runs with JSON logging only.
//!
//! Transport is gRPC (tonic). If your collector only speaks HTTP, swap
//! `opentelemetry-otlp`'s feature list in Cargo.toml from `grpc-tonic` to
//! `http-proto` (or `http-json`) + `reqwest-client`, then change the
//! `.with_tonic()` call below to `.with_http()`.

use opentelemetry::trace::TracerProvider as _;
use opentelemetry::KeyValue;
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::trace::Tracer as SdkTracer;
use opentelemetry_sdk::Resource;
use tracing::Subscriber;
use tracing_subscriber::{registry::LookupSpan, Layer};

pub fn build_otel_layer<S>() -> Option<Box<dyn Layer<S> + Send + Sync + 'static>>
where
    S: Subscriber + for<'span> LookupSpan<'span> + Send + Sync,
{
    let endpoint = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT").ok()?;
    if endpoint.is_empty() {
        return None;
    }

    let tracer = match init_tracer(&endpoint) {
        Ok(t) => t,
        Err(err) => {
            eprintln!("[otel] tracer init failed: {}", err);
            return None;
        }
    };

    let layer = tracing_opentelemetry::layer().with_tracer(tracer);
    Some(Box::new(layer))
}

fn init_tracer(endpoint: &str) -> Result<SdkTracer, String> {
    let service_name = std::env::var("OTEL_SERVICE_NAME")
        .unwrap_or_else(|_| "forge-service".to_string());

    let exporter = opentelemetry_otlp::SpanExporter::builder()
        .with_tonic()
        .with_endpoint(endpoint)
        .build()
        .map_err(|e| format!("build exporter: {e}"))?;

    let provider = opentelemetry_sdk::trace::TracerProvider::builder()
        .with_batch_exporter(exporter, opentelemetry_sdk::runtime::Tokio)
        .with_resource(Resource::new(vec![KeyValue::new(
            "service.name",
            service_name.clone(),
        )]))
        .build();

    // Register provider globally so crates using the opentelemetry API
    // (e.g. axum-tracing-opentelemetry integrations) pick it up.
    opentelemetry::global::set_tracer_provider(provider.clone());

    Ok(provider.tracer(service_name))
}
