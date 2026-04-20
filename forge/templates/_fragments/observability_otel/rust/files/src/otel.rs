//! OpenTelemetry setup for Axum/Rust backends.
//!
//! Uses ``tracing-opentelemetry`` to bridge the ``tracing`` crate (which
//! the base template already uses for structured logs) to OTLP. When
//! ``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset, the exporter is omitted so
//! local dev without a collector still works.

use opentelemetry::global;
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::{runtime, trace::TracerProvider, Resource};
use tracing_subscriber::{layer::SubscriberExt, EnvFilter, Registry};

pub fn configure_otel(service_name: &str) -> anyhow::Result<()> {
    let endpoint = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT").ok();

    let resource = Resource::new(vec![
        opentelemetry::KeyValue::new("service.name", service_name.to_string()),
    ]);

    let mut provider_builder = TracerProvider::builder().with_resource(resource);

    if let Some(endpoint) = endpoint {
        let exporter = opentelemetry_otlp::new_exporter()
            .tonic()
            .with_endpoint(endpoint)
            .build_span_exporter()?;
        provider_builder = provider_builder.with_batch_exporter(exporter, runtime::Tokio);
    }

    let provider = provider_builder.build();
    global::set_tracer_provider(provider.clone());

    let telemetry = tracing_opentelemetry::layer().with_tracer(provider.tracer(service_name.to_string()));
    let subscriber = Registry::default()
        .with(EnvFilter::from_default_env())
        .with(telemetry);
    tracing::subscriber::set_global_default(subscriber)?;

    Ok(())
}
