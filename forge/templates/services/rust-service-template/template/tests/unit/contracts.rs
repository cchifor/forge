use crate::errors::{AppError, ErrorCode};
use axum::response::IntoResponse;
use http_body_util::BodyExt;

#[tokio::test]
async fn error_envelopes_preserve_status_and_hide_internal_details() {
    let cases = vec![
        (AppError::not_found("Item", "one"), 404, "NOT_FOUND"),
        (
            AppError::already_exists("Item", "one"),
            409,
            "ALREADY_EXISTS",
        ),
        (
            AppError::duplicate_entry("Item", "name", "one"),
            409,
            "DUPLICATE_ENTRY",
        ),
        (AppError::read_only("Item"), 403, "READ_ONLY"),
        (
            AppError::Validation("invalid".into()),
            422,
            "VALIDATION_FAILED",
        ),
        (AppError::AuthRequired, 401, "AUTH_REQUIRED"),
        (
            AppError::PermissionDenied("denied".into()),
            403,
            "PERMISSION_DENIED",
        ),
        (
            AppError::ForeignKeyViolation("reference".into()),
            409,
            "FOREIGN_KEY_VIOLATION",
        ),
        (
            AppError::ConstraintViolation("constraint".into()),
            409,
            "CONSTRAINT_VIOLATION",
        ),
        (AppError::RateLimited("retry".into()), 429, "RATE_LIMITED"),
        (
            AppError::DependencyUnavailable {
                dependency: "upstream".into(),
            },
            503,
            "DEPENDENCY_UNAVAILABLE",
        ),
        (
            AppError::DatabaseUnavailable("connection".into()),
            503,
            "DATABASE_UNAVAILABLE",
        ),
        (
            AppError::DatabaseTimeout("deadline".into()),
            503,
            "DATABASE_TIMEOUT",
        ),
        (
            AppError::Internal("private connection secret".into()),
            500,
            "INTERNAL_ERROR",
        ),
    ];
    for (error, status, code) in cases {
        let response = error.into_response();
        assert_eq!(response.status().as_u16(), status);
        assert_eq!(response.headers()["content-type"], "application/json");
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let data: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(data["error"]["code"], code);
        assert!(data["error"]["context"].is_object());
        assert!(data["error"]["correlation_id"].is_string());
        assert!(!String::from_utf8_lossy(&body).contains("private connection secret"));
    }
    assert_eq!(ErrorCode::InvalidInput.status().as_u16(), 422);
    assert_eq!(ErrorCode::InvalidInput.as_str(), "INVALID_INPUT");
}

#[test]
fn database_failures_map_to_public_contract() {
    for (error, expected) in [
        (sqlx::Error::RowNotFound, ErrorCode::NotFound),
        (sqlx::Error::PoolTimedOut, ErrorCode::DatabaseUnavailable),
        (sqlx::Error::PoolClosed, ErrorCode::DatabaseUnavailable),
        (
            sqlx::Error::Protocol("private".into()),
            ErrorCode::InternalError,
        ),
    ] {
        assert_eq!(AppError::from(error).code(), expected);
    }
}

#[test]
fn testing_configuration_loads_defaults_and_profile() {
    let cfg = crate::config::AppConfig::load_with(crate::config::LoadOptions {
        project_root: Some(std::env::current_dir().unwrap()),
        env: Some("testing".into()),
    })
    .unwrap();
    assert!(cfg.server.port > 0);
    assert!(cfg.server.cors.enabled);
}

#[test]
fn missing_config_files_use_safe_defaults() {
    let directory = std::env::temp_dir().join(format!("forge-config-{}", uuid::Uuid::new_v4()));
    let cfg = crate::config::AppConfig::load_with(crate::config::LoadOptions {
        project_root: Some(directory),
        env: Some("testing".into()),
    })
    .unwrap();
    assert!(cfg.server.port > 0);
    assert!(!cfg.server.cors.allow_credentials);
    assert!(cfg.db.pool_max >= cfg.db.pool_min);
}
