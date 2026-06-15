//! Axum extractor for [`IdentityContext`].
//!
//! Lets handlers consume the verified identity directly in their
//! signature instead of reaching into request extensions:
//!
//! ```no_run
//! use axum::Json;
//! use platform_auth::IdentityContext;
//!
//! async fn list_things(identity: IdentityContext) -> Json<Vec<String>> {
//!     // identity.tenant_id, identity.scopes, identity.has_scope(...) etc.
//!     # let _ = identity;
//!     Json(vec![])
//! }
//! ```
//!
//! Requires the [`AuthLayer`](crate::layer::AuthLayer) (or another
//! middleware that inserts an [`IdentityContext`] into the request
//! extensions) to have run earlier in the stack. Without it, the
//! extractor short-circuits with a `401 Unauthorized` mapped from
//! [`AuthError::InvalidToken`] — fail-closed semantics so a
//! mis-wired router can't accidentally serve unauthenticated
//! traffic.
//!
//! Gated behind the `axum` feature; consumers of the bare verifier
//! don't pay the cost.

use axum::{extract::FromRequestParts, http::request::Parts, response::IntoResponse};

use crate::{errors::AuthError, identity::IdentityContext};

// axum 0.8 dropped the async-trait re-export; `FromRequestParts` is a
// native async-fn trait now, so no macro wrapper is needed.
impl<S> FromRequestParts<S> for IdentityContext
where
    S: Send + Sync,
{
    type Rejection = IdentityRejection;

    async fn from_request_parts(parts: &mut Parts, _state: &S) -> Result<Self, Self::Rejection> {
        parts
            .extensions
            .get::<IdentityContext>()
            .cloned()
            .ok_or(IdentityRejection)
    }
}

/// Rejection emitted when the extractor runs without an
/// [`IdentityContext`] in the request extensions.
///
/// The body matches the cross-language RFC 7807 problem-response
/// shape used by the Node `platformAuthPlugin` and the Rust
/// `from_fn` middleware in `platform_auth_rust_middleware` — same
/// `https://forge.dev/errors/<reason>` URI prefix, same `reason`
/// slug, same `WWW-Authenticate: Bearer` challenge.
pub struct IdentityRejection;

impl IntoResponse for IdentityRejection {
    fn into_response(self) -> axum::response::Response {
        let err = AuthError::InvalidToken("no verified identity bound to request".into());
        crate::layer::auth_error_response(err)
    }
}

/// Optional version of [`IdentityContext`] for routes that *may* be
/// served unauthenticated (e.g. mixed public/private endpoints).
///
/// Returns `Some(identity)` when the auth middleware found a
/// verified identity, or `None` for skipped paths (`/health`,
/// `/metrics`, etc.) or otherwise unauthenticated requests. NEVER
/// short-circuits — handlers must explicitly check.
pub struct OptionalIdentity(pub Option<IdentityContext>);

impl<S> FromRequestParts<S> for OptionalIdentity
where
    S: Send + Sync,
{
    type Rejection = std::convert::Infallible;

    async fn from_request_parts(parts: &mut Parts, _state: &S) -> Result<Self, Self::Rejection> {
        Ok(Self(parts.extensions.get::<IdentityContext>().cloned()))
    }
}
