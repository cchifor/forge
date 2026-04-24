//! RFC-007 error contract for the Rust backend.
//!
//! Every HTTP error response is serialized into the canonical envelope:
//!
//! ```json
//! {
//!   "error": {
//!     "code": "NOT_FOUND",
//!     "message": "Item 'abc' not found",
//!     "type": "NotFoundError",
//!     "context": {},
//!     "correlation_id": ""
//!   }
//! }
//! ```
//!
//! The `correlation_id` body field is best-effort; the authoritative
//! correlation id always travels in the `X-Request-Id` response header
//! (propagated by `middleware::correlation`). Handlers that wish to
//! echo it in the body can attach via `AppError::with_correlation`.

use axum::http::{HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde::Serialize;
use serde_json::{json, Value};

/// Canonical error codes shared across Python / Node / Rust backends.
/// Keep this list in sync with RFC-007.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ErrorCode {
    AuthRequired,
    PermissionDenied,
    ReadOnly,
    NotFound,
    AlreadyExists,
    DuplicateEntry,
    ForeignKeyViolation,
    ConstraintViolation,
    ValidationFailed,
    InvalidInput,
    RateLimited,
    InternalError,
    DatabaseUnavailable,
    DatabaseTimeout,
    DependencyUnavailable,
}

impl ErrorCode {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::AuthRequired => "AUTH_REQUIRED",
            Self::PermissionDenied => "PERMISSION_DENIED",
            Self::ReadOnly => "READ_ONLY",
            Self::NotFound => "NOT_FOUND",
            Self::AlreadyExists => "ALREADY_EXISTS",
            Self::DuplicateEntry => "DUPLICATE_ENTRY",
            Self::ForeignKeyViolation => "FOREIGN_KEY_VIOLATION",
            Self::ConstraintViolation => "CONSTRAINT_VIOLATION",
            Self::ValidationFailed => "VALIDATION_FAILED",
            Self::InvalidInput => "INVALID_INPUT",
            Self::RateLimited => "RATE_LIMITED",
            Self::InternalError => "INTERNAL_ERROR",
            Self::DatabaseUnavailable => "DATABASE_UNAVAILABLE",
            Self::DatabaseTimeout => "DATABASE_TIMEOUT",
            Self::DependencyUnavailable => "DEPENDENCY_UNAVAILABLE",
        }
    }

    pub fn status(&self) -> StatusCode {
        match self {
            Self::AuthRequired => StatusCode::UNAUTHORIZED,
            Self::PermissionDenied | Self::ReadOnly => StatusCode::FORBIDDEN,
            Self::NotFound => StatusCode::NOT_FOUND,
            Self::AlreadyExists
            | Self::DuplicateEntry
            | Self::ForeignKeyViolation
            | Self::ConstraintViolation => StatusCode::CONFLICT,
            Self::ValidationFailed | Self::InvalidInput => StatusCode::UNPROCESSABLE_ENTITY,
            Self::RateLimited => StatusCode::TOO_MANY_REQUESTS,
            Self::InternalError => StatusCode::INTERNAL_SERVER_ERROR,
            Self::DatabaseUnavailable
            | Self::DatabaseTimeout
            | Self::DependencyUnavailable => StatusCode::SERVICE_UNAVAILABLE,
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("{entity} '{id}' not found")]
    NotFound { entity: String, id: String },

    #[error("{entity} '{name}' already exists")]
    AlreadyExists { entity: String, name: String },

    #[error("duplicate {entity}: {field}='{value}' already exists")]
    DuplicateEntry {
        entity: String,
        field: String,
        value: String,
    },

    #[error("{0}")]
    Validation(String),

    #[error("Authentication required")]
    AuthRequired,

    #[error("{0}")]
    PermissionDenied(String),

    #[error("{resource} is read-only")]
    ReadOnly { resource: String },

    #[error("{0}")]
    ForeignKeyViolation(String),

    #[error("{0}")]
    ConstraintViolation(String),

    #[error("{0}")]
    RateLimited(String),

    #[error("{dependency} is unavailable")]
    DependencyUnavailable { dependency: String },

    #[error("database is unavailable: {0}")]
    DatabaseUnavailable(String),

    #[error("database operation timed out: {0}")]
    DatabaseTimeout(String),

    #[error("internal error: {0}")]
    Internal(String),
}

impl AppError {
    pub fn not_found(entity: impl Into<String>, id: impl Into<String>) -> Self {
        Self::NotFound {
            entity: entity.into(),
            id: id.into(),
        }
    }

    pub fn already_exists(entity: impl Into<String>, name: impl Into<String>) -> Self {
        Self::AlreadyExists {
            entity: entity.into(),
            name: name.into(),
        }
    }

    pub fn duplicate_entry(
        entity: impl Into<String>,
        field: impl Into<String>,
        value: impl Into<String>,
    ) -> Self {
        Self::DuplicateEntry {
            entity: entity.into(),
            field: field.into(),
            value: value.into(),
        }
    }

    pub fn read_only(resource: impl Into<String>) -> Self {
        Self::ReadOnly {
            resource: resource.into(),
        }
    }

    pub fn code(&self) -> ErrorCode {
        match self {
            Self::NotFound { .. } => ErrorCode::NotFound,
            Self::AlreadyExists { .. } => ErrorCode::AlreadyExists,
            Self::DuplicateEntry { .. } => ErrorCode::DuplicateEntry,
            Self::Validation(_) => ErrorCode::ValidationFailed,
            Self::AuthRequired => ErrorCode::AuthRequired,
            Self::PermissionDenied(_) => ErrorCode::PermissionDenied,
            Self::ReadOnly { .. } => ErrorCode::ReadOnly,
            Self::ForeignKeyViolation(_) => ErrorCode::ForeignKeyViolation,
            Self::ConstraintViolation(_) => ErrorCode::ConstraintViolation,
            Self::RateLimited(_) => ErrorCode::RateLimited,
            Self::DependencyUnavailable { .. } => ErrorCode::DependencyUnavailable,
            Self::DatabaseUnavailable(_) => ErrorCode::DatabaseUnavailable,
            Self::DatabaseTimeout(_) => ErrorCode::DatabaseTimeout,
            Self::Internal(_) => ErrorCode::InternalError,
        }
    }

    pub fn type_name(&self) -> &'static str {
        match self {
            Self::NotFound { .. } => "NotFoundError",
            Self::AlreadyExists { .. } => "AlreadyExistsError",
            Self::DuplicateEntry { .. } => "DuplicateEntryError",
            Self::Validation(_) => "ValidationError",
            Self::AuthRequired => "AuthRequiredError",
            Self::PermissionDenied(_) => "PermissionDeniedError",
            Self::ReadOnly { .. } => "ReadOnlyError",
            Self::ForeignKeyViolation(_) => "ForeignKeyViolationError",
            Self::ConstraintViolation(_) => "ConstraintViolationError",
            Self::RateLimited(_) => "RateLimitedError",
            Self::DependencyUnavailable { .. } => "DependencyUnavailableError",
            Self::DatabaseUnavailable(_) => "DatabaseUnavailableError",
            Self::DatabaseTimeout(_) => "DatabaseTimeoutError",
            Self::Internal(_) => "InternalError",
        }
    }

    fn context(&self) -> Value {
        match self {
            Self::NotFound { entity, id } => json!({ "entity": entity, "id": id }),
            Self::AlreadyExists { entity, name } => {
                json!({ "entity": entity, "name": name })
            }
            Self::DuplicateEntry { entity, field, value } => {
                json!({ "entity": entity, "field": field, "value": value })
            }
            Self::ReadOnly { resource } => json!({ "resource": resource }),
            Self::DependencyUnavailable { dependency } => json!({ "dependency": dependency }),
            _ => json!({}),
        }
    }
}

#[derive(Debug, Serialize)]
struct ErrorBody<'a> {
    code: &'a str,
    message: String,
    #[serde(rename = "type")]
    type_name: &'a str,
    context: Value,
    correlation_id: String,
}

#[derive(Debug, Serialize)]
struct ErrorEnvelope<'a> {
    error: ErrorBody<'a>,
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let code = self.code();
        let status = code.status();

        if matches!(status, StatusCode::INTERNAL_SERVER_ERROR) {
            tracing::error!(error = %self, "Internal error");
        } else {
            tracing::warn!(error = %self, "Request failed");
        }

        let body = ErrorEnvelope {
            error: ErrorBody {
                code: code.as_str(),
                message: self.to_string(),
                type_name: self.type_name(),
                context: self.context(),
                correlation_id: String::new(),
            },
        };

        let mut response = (status, Json(body)).into_response();
        // Ensure a stable content type even when the framework strips it.
        response.headers_mut().insert(
            axum::http::header::CONTENT_TYPE,
            HeaderValue::from_static("application/json"),
        );
        response
    }
}

impl From<sqlx::Error> for AppError {
    fn from(err: sqlx::Error) -> Self {
        tracing::error!("Database error: {:?}", err);
        match err {
            sqlx::Error::RowNotFound => AppError::NotFound {
                entity: "Row".to_string(),
                id: "unknown".to_string(),
            },
            sqlx::Error::PoolTimedOut | sqlx::Error::PoolClosed => {
                AppError::DatabaseUnavailable("connection pool exhausted".to_string())
            }
            _ => AppError::Internal("database error".to_string()),
        }
    }
}
