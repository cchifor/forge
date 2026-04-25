//! Shared test utilities — see ``docs/testing-generated-backends.md``.
//!
//! Mirrors the Python and Node helpers so a fragment author writing
//! tests in any backend uses the same vocabulary.

use std::collections::HashMap;
use uuid::Uuid;

pub const DEFAULT_USER_ID_STR: &str = "00000000-0000-0000-0000-000000000001";

#[derive(Clone, Debug)]
pub struct TenantTestContext {
    pub user_id: Uuid,
    pub customer_id: Uuid,
    pub email: String,
    pub roles: Vec<String>,
}

impl Default for TenantTestContext {
    fn default() -> Self {
        let id = Uuid::parse_str(DEFAULT_USER_ID_STR).expect("static uuid");
        Self {
            user_id: id,
            customer_id: id,
            email: "test@localhost".to_string(),
            roles: vec!["user".to_string()],
        }
    }
}

pub fn tenant_factory() -> TenantTestContext {
    TenantTestContext::default()
}

pub fn authenticated_headers(ctx: &TenantTestContext) -> HashMap<&'static str, String> {
    let mut headers = HashMap::new();
    headers.insert("x-gatekeeper-user-id", ctx.user_id.to_string());
    headers.insert("x-gatekeeper-email", ctx.email.clone());
    headers.insert("x-gatekeeper-roles", ctx.roles.join(","));
    if ctx.customer_id != ctx.user_id {
        headers.insert("x-customer-id", ctx.customer_id.to_string());
    }
    headers
}

pub mod errors {
    //! Assertions over the RFC-007 error envelope.

    use serde::Deserialize;

    #[derive(Debug, Deserialize)]
    pub struct ErrorBody {
        pub code: String,
        pub message: String,
        #[serde(rename = "type")]
        pub type_name: String,
        pub context: serde_json::Value,
        pub correlation_id: String,
    }

    #[derive(Debug, Deserialize)]
    pub struct ErrorEnvelope {
        pub error: ErrorBody,
    }

    pub fn parse_envelope(body: &[u8]) -> ErrorEnvelope {
        serde_json::from_slice(body).expect("response body must be RFC-007 envelope JSON")
    }

    pub fn assert_envelope(envelope: &ErrorEnvelope, code: &str) {
        assert_eq!(envelope.error.code, code, "expected code {code:?}");
    }
}
