//! Error port — capability contract for RFC-007 error-envelope serialisation.
//!
//! Promotes the hand-written error-handler code already shipping in the
//! base template (`src/errors.rs::IntoResponse for AppError`) into a
//! swappable port. The base template's `IntoResponse` impl keeps
//! emitting the envelope as-is (that's the default behaviour); plugins
//! shipping custom envelope shapes implement [`ErrorPort`] and register
//! their adapter in place of [`default::DefaultErrorPort`].
//!
//! The port surface is intentionally tiny — one [`ErrorPort::serialize`]
//! method that takes an exception and returns the JSON-ready envelope.
//! HTTP status, logging, and correlation-id propagation stay in the
//! central `IntoResponse` impl; the port owns only the wire shape.
//! See `docs/rfcs/RFC-007-error-contract.md` for the canonical envelope
//! spec and the cross-language port siblings:
//!
//! - Python: `src/app/ports/error_port.py`
//! - Node:   `src/app/ports/error-port.ts`
//!
//! Adapters that mint custom codes (or change context shape) MUST keep
//! the top-level `{"error": {...}}` wrapper and the five required
//! fields (`code`, `message`, `type`, `context`, `correlation_id`);
//! otherwise the unified frontend client breaks. New `code` enum
//! values get added to [`crate::errors::ErrorCode`] so two features
//! can't silently claim the same mapping.

pub mod default;

use serde::Serialize;
use serde_json::Value;

/// The RFC-007 envelope payload — the inner body of `{ "error": {...} }`.
#[derive(Debug, Clone, Serialize)]
pub struct ErrorBody {
    /// RFC-007 enum, machine-readable, stable across versions.
    pub code: String,
    /// Human-readable, UI-safe. Never contains stack or PII.
    pub message: String,
    /// Concrete error class name — for diagnostic UIs / support tickets.
    #[serde(rename = "type")]
    pub type_name: String,
    /// Freeform structured data; `{}` when not applicable.
    pub context: Value,
    /// Request correlation id — echoes `X-Correlation-Id`. Adapters
    /// with no request context return an empty string; the central
    /// error middleware fills it in.
    pub correlation_id: String,
}

/// The RFC-007 envelope wrapper — top-level `{ "error": {...} }`.
#[derive(Debug, Clone, Serialize)]
pub struct ErrorEnvelope {
    pub error: ErrorBody,
}

/// Serialise a raised error into the RFC-007 envelope.
///
/// Implementations are pure — they MUST NOT mutate the error or
/// perform I/O. The central error middleware calls [`serialize`] once
/// per request, then writes the returned envelope as the response body
/// with the matching HTTP status (mapped via
/// [`crate::errors::ErrorCode::status`]).
///
/// [`serialize`]: ErrorPort::serialize
///
/// The `exc` parameter carries a `+ 'static` bound so the default
/// adapter can `downcast_ref::<AppError>()` — the `std::error::Error`
/// `Any`-based downcast machinery is `'static`-only. Concrete errors
/// raised by `axum` handlers (and bridged via `AppError`) are already
/// `'static`; the bound is documentary, not a behaviour change.
pub trait ErrorPort: Send + Sync {
    fn serialize(&self, exc: &(dyn std::error::Error + 'static)) -> ErrorEnvelope;
}
