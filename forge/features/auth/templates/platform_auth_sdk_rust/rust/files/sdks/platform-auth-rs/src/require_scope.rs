//! Per-route scope enforcement Tower layer.
//!
//! Mirrors Python `platform_auth.auth_guard.require_scope` and Node
//! `requireScope`: runs AFTER [`AuthLayer`](crate::layer::AuthLayer)
//! so an [`IdentityContext`] is already bound to the request. Reads
//! it, asserts the identity satisfies *every* configured scope
//! (with wildcard support), and short-circuits with a `403 Forbidden`
//! mapped from [`AuthError::ScopeRequired`] otherwise.
//!
//! ```no_run
//! use std::sync::Arc;
//! use axum::{routing::get, Router};
//! use platform_auth::{AuthGuard, AuthGuardConfig, AuthLayer, JwksCache, RequireScope};
//!
//! # async fn _example() -> Result<(), Box<dyn std::error::Error>> {
//! let jwks = Arc::new(JwksCache::default()?);
//! let auth = Arc::new(AuthGuard::new(AuthGuardConfig::new("svc-things", jwks))?);
//!
//! let app = Router::<()>::new()
//!     // require_scope MUST come AFTER AuthLayer in the layer chain;
//!     // .layer() applies in reverse, so list it first here.
//!     .route(
//!         "/things",
//!         get(|| async { "ok" }).layer(RequireScope::new(["things:read"])),
//!     )
//!     .layer(AuthLayer::new(auth));
//! # Ok(())
//! # }
//! ```
//!
//! Wildcard semantics match `scope_satisfies`: `things:*` satisfies
//! `things:read` / `things:write` / etc.; `*` is god-mode.
//!
//! Gated behind the `axum` feature.

use std::{
    collections::HashSet,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

use axum::{body::Body, extract::Request, response::Response};
use tower::{Layer, Service};

use crate::{errors::AuthError, identity::IdentityContext, layer::auth_error_response};

/// Tower [`Layer`] that enforces every required scope on the
/// inbound `IdentityContext`.
#[derive(Clone)]
pub struct RequireScope {
    required: Arc<HashSet<String>>,
}

impl RequireScope {
    pub fn new<I, S>(required: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        Self {
            required: Arc::new(required.into_iter().map(Into::into).collect()),
        }
    }
}

impl<S> Layer<S> for RequireScope {
    type Service = RequireScopeService<S>;

    fn layer(&self, inner: S) -> Self::Service {
        RequireScopeService {
            inner,
            required: self.required.clone(),
        }
    }
}

#[derive(Clone)]
pub struct RequireScopeService<S> {
    inner: S,
    required: Arc<HashSet<String>>,
}

impl<S> Service<Request<Body>> for RequireScopeService<S>
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

    fn call(&mut self, request: Request<Body>) -> Self::Future {
        let cloned = self.inner.clone();
        let mut inner = std::mem::replace(&mut self.inner, cloned);
        let required = self.required.clone();

        Box::pin(async move {
            // Read the identity from request extensions. Missing →
            // mis-wired router (RequireScope used without AuthLayer).
            // Fail closed.
            let Some(identity) = request.extensions().get::<IdentityContext>().cloned() else {
                return Ok(auth_error_response(AuthError::InvalidToken(
                    "no verified identity bound to request".into(),
                )));
            };

            // No required scopes? Pass through. (RequireScope::new([])
            // is a meaningful no-op — useful when a decorator is
            // applied unconditionally and the actual list comes from
            // config.)
            if required.is_empty() {
                return inner.call(request).await;
            }

            let missing: HashSet<String> = required
                .iter()
                .filter(|scope| !identity.has_scope(scope))
                .cloned()
                .collect();
            if !missing.is_empty() {
                return Ok(auth_error_response(AuthError::ScopeRequired { missing }));
            }

            inner.call(request).await
        })
    }
}
