//! Tower [`Layer`] wrapping [`AuthGuard`] for Axum integration.
//!
//! Mirrors Python's `AuthContextMiddleware` and Node's
//! `platformAuthPlugin`: extracts the bearer once per request,
//! verifies via [`AuthGuard`], inserts the resulting
//! [`IdentityContext`] into the request extensions, and passes
//! control downstream. On verification failure, short-circuits
//! with an RFC 7807 problem response.
//!
//! ```no_run
//! use std::sync::Arc;
//! use axum::Router;
//! use platform_auth::{AuthGuard, AuthGuardConfig, AuthLayer, JwksCache};
//!
//! # async fn _example() -> Result<(), Box<dyn std::error::Error>> {
//! let jwks = Arc::new(JwksCache::default()?);
//! jwks.register_issuer("http://gatekeeper:5000",
//!                       "http://gatekeeper:5000/auth/jwks").await?;
//! let auth = Arc::new(AuthGuard::new(AuthGuardConfig::new("svc-things", jwks))?);
//!
//! let app = Router::<()>::new()
//!     .route("/things", axum::routing::get(|| async { "ok" }))
//!     .layer(AuthLayer::new(auth));
//! # Ok(())
//! # }
//! ```
//!
//! Skip-list (`/health`, `/metrics`, `/docs`, `/openapi.json`) is
//! configurable; defaults match the Python middleware and Node plugin
//! so cross-language probe behavior is identical.
//!
//! Gated behind the `axum` feature.

use std::{
    collections::HashSet,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

use axum::{
    body::Body,
    extract::Request,
    http::{header, HeaderValue, StatusCode},
    response::{IntoResponse, Json, Response},
};
use serde_json::json;
use tower::{Layer, Service};

use crate::{auth_guard::AuthGuard, errors::AuthError};

/// Default skip-list — same set the Python middleware and Node plugin
/// honor. Pin so cross-language probe semantics never drift.
pub const DEFAULT_EXCLUDED_PATHS: &[&str] = &[
    "/health",
    "/health/live",
    "/health/ready",
    "/metrics",
    "/docs",
    "/openapi.json",
];

/// Configurable Tower layer that runs an [`AuthGuard`] on every
/// non-skipped request.
#[derive(Clone)]
pub struct AuthLayer {
    auth: Arc<AuthGuard>,
    excluded: Arc<HashSet<String>>,
}

impl AuthLayer {
    /// Build a new layer using the default skip-list (matches Python
    /// and Node).
    pub fn new(auth: Arc<AuthGuard>) -> Self {
        Self::with_excluded_paths(auth, DEFAULT_EXCLUDED_PATHS.iter().copied())
    }

    /// Build with a custom skip-list. Pass an empty iterator to verify
    /// every path (rare — useful for tests).
    pub fn with_excluded_paths<I, S>(auth: Arc<AuthGuard>, paths: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let excluded: HashSet<String> = paths.into_iter().map(Into::into).collect();
        Self {
            auth,
            excluded: Arc::new(excluded),
        }
    }
}

impl<S> Layer<S> for AuthLayer {
    type Service = AuthService<S>;

    fn layer(&self, inner: S) -> Self::Service {
        AuthService {
            inner,
            auth: self.auth.clone(),
            excluded: self.excluded.clone(),
        }
    }
}

/// Tower [`Service`] produced by [`AuthLayer::layer`].
#[derive(Clone)]
pub struct AuthService<S> {
    inner: S,
    auth: Arc<AuthGuard>,
    excluded: Arc<HashSet<String>>,
}

impl<S> Service<Request<Body>> for AuthService<S>
where
    S: Service<Request<Body>, Response = Response> + Clone + Send + 'static,
    S::Future: Send + 'static,
    S::Error: Send + 'static,
{
    type Response = Response;
    type Error = S::Error;
    type Future = Pin<Box<dyn std::future::Future<Output = Result<Response, S::Error>> + Send>>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, mut request: Request<Body>) -> Self::Future {
        // Tower's documented pattern for stateful clone-on-call. The
        // inner service's `poll_ready` was reserved on `self` (the
        // original); cloning here gives us a fresh call slot. Without
        // the swap, the cloned inner could be in an un-readied state.
        let cloned = self.inner.clone();
        let mut inner = std::mem::replace(&mut self.inner, cloned);
        let auth = self.auth.clone();
        let excluded = self.excluded.clone();

        Box::pin(async move {
            // Skip the configured paths so probes work without auth.
            let path = request.uri().path().to_string();
            if excluded.contains(&path) {
                return inner.call(request).await;
            }

            // Extract the bearer.
            let token = match extract_bearer(&request) {
                Ok(t) => t,
                Err(err) => return Ok(auth_error_response(err)),
            };

            // Verify.
            let identity = match auth.verify(&token).await {
                Ok(id) => id,
                Err(err) => return Ok(auth_error_response(err)),
            };

            // Bind to request extensions for downstream handlers /
            // extractors (`FromRequestParts<IdentityContext>` reads
            // from here).
            request.extensions_mut().insert(identity);

            inner.call(request).await
        })
    }
}

/// Pull the bearer out of an axum `Request`. Mirrors the helper in
/// `platform_auth_rust_middleware`'s `auth.rs` so the wire-protocol
/// + error-message text stays identical between the two integration
/// paths.
fn extract_bearer(request: &Request<Body>) -> Result<String, AuthError> {
    let value = request
        .headers()
        .get(header::AUTHORIZATION)
        .ok_or_else(|| AuthError::InvalidToken("missing Authorization header".into()))?;
    let raw = value
        .to_str()
        .map_err(|_| AuthError::InvalidToken("Authorization header is not valid UTF-8".into()))?;
    let (prefix, token) = raw
        .split_once(' ')
        .ok_or_else(|| AuthError::InvalidToken("Authorization header is not a Bearer token".into()))?;
    if !prefix.eq_ignore_ascii_case("bearer") || token.is_empty() {
        return Err(AuthError::InvalidToken(
            "Authorization header is not a Bearer token".into(),
        ));
    }
    Ok(token.trim().to_string())
}

/// Translate an [`AuthError`] into an RFC 7807 problem response.
///
/// Same `https://forge.dev/errors/<reason>` URI prefix as the Node
/// plugin and the `from_fn` middleware in
/// `platform_auth_rust_middleware` — cross-language client-dispatch
/// contract preserved. `pub(crate)` so the extractor's
/// `IdentityRejection` reuses it.
pub(crate) fn auth_error_response(err: AuthError) -> Response {
    let status = StatusCode::from_u16(err.status_code()).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let mut response = Json(json!({
        "type": format!("https://forge.dev/errors/{}", err.reason()),
        "title": err.reason(),
        "status": status.as_u16(),
        "detail": err.to_string(),
    }))
    .into_response();
    *response.status_mut() = status;
    if status == StatusCode::UNAUTHORIZED {
        // RFC 6750 §3 — every 401 from a bearer-protected resource carries
        // `WWW-Authenticate: Bearer`. `from_static` is infallible for ASCII.
        response
            .headers_mut()
            .insert(header::WWW_AUTHENTICATE, HeaderValue::from_static("Bearer"));
    }
    response
}
