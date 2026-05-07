//! OpenTelemetry setup for Axum/Rust backends — stub.
//!
//! ``opentelemetry`` 0.27's exporter / runtime API differs across patch
//! releases (``new_exporter``, ``runtime::Tokio``, ``TracerProvider::tracer``
//! all moved); pinning the integration here would lock the generated
//! service to whatever shape happened on the day of generation. Instead,
//! ship a no-op stub so generated services compile out of the box and
//! let users wire OTel against their concrete crate versions.
//!
//! Fill ``configure_otel`` in once your project pins ``opentelemetry`` /
//! ``opentelemetry-sdk`` / ``opentelemetry-otlp`` / ``tracing-opentelemetry``
//! to specific patch versions. The signature below is intentionally simple
//! to keep the call site in ``main.rs`` ergonomic.

pub fn configure_otel(_service_name: &str) -> Result<(), Box<dyn std::error::Error>> {
    Ok(())
}
