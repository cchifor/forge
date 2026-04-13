use axum::extract::FromRequestParts;
use axum::http::request::Parts;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;
use uuid::Uuid;

/// Tenant context extracted from Gatekeeper ForwardAuth headers.
///
/// Gatekeeper injects these headers after validating the session:
///   X-Gatekeeper-User-Id, X-Gatekeeper-Email, X-Gatekeeper-Tenant, X-Gatekeeper-Roles
///
/// For service-to-service calls, the caller propagates these headers directly.
#[derive(Debug, Clone)]
pub struct TenantContext {
    pub user_id: Uuid,
    pub email: String,
    pub customer_id: Uuid,
    pub roles: Vec<String>,
}

pub struct TenantRejection;

impl IntoResponse for TenantRejection {
    fn into_response(self) -> Response {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({
                "error": "401",
                "message": "Authentication required"
            })),
        )
            .into_response()
    }
}

impl<S> FromRequestParts<S> for TenantContext
where
    S: Send + Sync,
{
    type Rejection = TenantRejection;

    async fn from_request_parts(parts: &mut Parts, _state: &S) -> Result<Self, Self::Rejection> {
        let user_id_str = parts
            .headers
            .get("x-gatekeeper-user-id")
            .and_then(|v| v.to_str().ok())
            .ok_or(TenantRejection)?;

        let user_id = Uuid::parse_str(user_id_str).map_err(|_| TenantRejection)?;

        let email = parts
            .headers
            .get("x-gatekeeper-email")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .to_string();

        let roles: Vec<String> = parts
            .headers
            .get("x-gatekeeper-roles")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .split(',')
            .filter(|s| !s.is_empty())
            .map(String::from)
            .collect();

        // x-customer-id is used for S2S tenant propagation (service account override)
        let customer_id_str = parts
            .headers
            .get("x-customer-id")
            .and_then(|v| v.to_str().ok())
            .unwrap_or(user_id_str);

        let customer_id = Uuid::parse_str(customer_id_str).unwrap_or(user_id);

        Ok(TenantContext {
            user_id,
            email,
            customer_id,
            roles,
        })
    }
}
