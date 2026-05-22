//! Default error-port adapter — RFC-007 envelope shape.
//!
//! Bridges the existing `crate::errors::AppError` machinery (the
//! `thiserror` enum + `IntoResponse` impl already shipping with the
//! base template) to the new [`ErrorPort`] trait. The adapter is a
//! thin wrapper — all the real work (code mapping, context surfacing)
//! lives in `crate::errors` and this adapter just composes the
//! envelope the port contract requires.
//!
//! Plugins shipping custom envelopes implement [`ErrorPort`]
//! themselves and register their type in place of this one (via the
//! project's dependency-injection container).

use serde_json::{Value, json};

use super::{ErrorBody, ErrorEnvelope, ErrorPort};
use crate::errors::AppError;

/// The reference adapter — emits the canonical RFC-007 envelope.
///
/// For known [`AppError`] variants, surfaces the registered code +
/// structured context. For everything else, falls back to
/// `INTERNAL_ERROR` with a redacted message — the central error
/// middleware logs the real error so operators can correlate via
/// `correlation_id`.
#[derive(Debug, Default, Clone, Copy)]
pub struct DefaultErrorPort;

impl ErrorPort for DefaultErrorPort {
    fn serialize(&self, exc: &dyn std::error::Error) -> ErrorEnvelope {
        if let Some(app_err) = exc.downcast_ref::<AppError>() {
            return ErrorEnvelope {
                error: ErrorBody {
                    code: app_err.code().as_str().to_string(),
                    message: app_err.to_string(),
                    type_name: app_err.type_name().to_string(),
                    context: app_err_context(app_err),
                    correlation_id: String::new(),
                },
            };
        }
        ErrorEnvelope {
            error: ErrorBody {
                code: "INTERNAL_ERROR".to_string(),
                // Redact the original message — the central middleware
                // logs the real error alongside the correlation id.
                message: "An unexpected error occurred".to_string(),
                type_name: "InternalError".to_string(),
                context: json!({}),
                correlation_id: String::new(),
            },
        }
    }
}

/// Surface the structured `context` field for an `AppError`. Mirrors
/// the per-variant context already serialised by
/// `crate::errors::AppError::context`, which is private — keeping a
/// minimal mirror here avoids leaking that helper across the crate.
fn app_err_context(exc: &AppError) -> Value {
    match exc {
        AppError::NotFound { entity, id } => json!({ "entity": entity, "id": id }),
        AppError::AlreadyExists { entity, name } => {
            json!({ "entity": entity, "name": name })
        }
        AppError::DuplicateEntry {
            entity,
            field,
            value,
        } => json!({ "entity": entity, "field": field, "value": value }),
        AppError::ReadOnly { resource } => json!({ "resource": resource }),
        AppError::DependencyUnavailable { dependency } => json!({ "dependency": dependency }),
        _ => json!({}),
    }
}
