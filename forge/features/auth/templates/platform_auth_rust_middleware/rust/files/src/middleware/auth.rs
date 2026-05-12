//! Auth middleware bootstrap — Rust service template.
//!
//! Wires the `platform-auth` Rust SDK into Axum's lifecycle. Constructs
//! an `AuthGuard` from environment-driven config at startup (via
//! `init_auth()`) and exposes a `from_fn`-compatible middleware
//! function that runs verification on every protected request and
//! inserts the verified `IdentityContext` into the request extensions.
//!
//! Mirrors the Python service-template's `app/middleware/auth_context.py`
//! and the Node service-template's `bootstrapAuth(app)` shape:
//! single-pass verification, request-state binding, RFC 7807 error
//! mapping (via the `AuthError::status_code()` slug), health/metrics/
//! docs skip-list.
//!
//! The full Tower-Layer-with-shared-state pattern lives in the SDK's
//! `layer.rs` (Phase 6 follow-up). Until that lands, this fragment
//! ships a simpler `OnceLock`-based wiring: `init_auth()` is called
//! once from `main.rs` before the server starts, and the middleware
//! reads from the global. This keeps Phase 7 self-contained without
//! requiring the SDK's `axum` feature to be activated.

use std::sync::{Arc, OnceLock};

use axum::{
    body::Body,
    extract::Request,
    http::{StatusCode, header},
    middleware::Next,
    response::{IntoResponse, Json, Response},
};
use platform_auth::{
    AuthError, AuthGuard, AuthGuardConfig, InMemoryIssuerTrustMap, JwksCache, JwksCacheOptions,
    StaticMayActPolicy, TenantTrust,
};
use serde_json::json;
use std::sync::Arc as StdArc;

/// Paths that skip auth verification — same set the Python middleware
/// and Node plugin honor. Pinned here so cross-language behavior is
/// identical.
const EXCLUDED_PATHS: &[&str] = &[
    "/health",
    "/health/live",
    "/health/ready",
    "/metrics",
    "/docs",
    "/openapi.json",
];

/// Process-wide AuthGuard. Initialized once from `init_auth()` before
/// the server starts; read by every middleware invocation.
static AUTH_GUARD: OnceLock<StdArc<AuthGuard>> = OnceLock::new();

/// Bootstrap the AuthGuard from environment variables.
///
/// Required env vars:
///   - `GATEKEEPER_ISSUER` — iss claim on internal JWTs (e.g.,
///     `http://gatekeeper:5000`).
///   - `SERVICE_AUDIENCE` — this service's expected aud claim.
///
/// Optional:
///   - `TENANT_ID_CLAIM` — defaults to `https://forge/tenant_id`.
///
/// Call this from `main()` before starting the Axum server. Returns
/// an error if env vars are missing or the JWKS endpoint is
/// unreachable at startup (fail-fast — the alternative is silent
/// 401-spamming under load).
pub async fn init_auth() -> Result<(), Box<dyn std::error::Error>> {
    let issuer = std::env::var("GATEKEEPER_ISSUER")
        .map_err(|_| "GATEKEEPER_ISSUER environment variable is required for auth wiring")?;
    let audience = std::env::var("SERVICE_AUDIENCE")
        .map_err(|_| "SERVICE_AUDIENCE environment variable is required for auth wiring")?;

    let jwks = StdArc::new(JwksCache::new(JwksCacheOptions::default())?);
    jwks.register_issuer(issuer.clone(), format!("{issuer}/auth/jwks"))
        .await?;

    let mut config = AuthGuardConfig::new(audience, jwks);
    if let Ok(claim) = std::env::var("TENANT_ID_CLAIM") {
        config.tenant_id_claim = claim;
    }
    // Default trust map: empty — production deployments must inject
    // a real one via a follow-up bootstrap. Default may-act policy:
    // deny-all (no actor authorized for any audience). Same defaults
    // as the Node `bootstrapAuth`.
    config.trust_map = Some(StdArc::new(InMemoryIssuerTrustMap::new()));
    config.may_act = Some(StdArc::new(StaticMayActPolicy::new(std::iter::empty::<(
        String,
        Vec<String>,
    )>())));

    let guard = AuthGuard::new(config)?;
    AUTH_GUARD
        .set(StdArc::new(guard))
        .map_err(|_| "init_auth() called more than once")?;
    // Suppress unused-import warnings when feature gating prunes
    // optional types. `Arc` and `TenantTrust` show up in extensions
    // helpers consumers reach for (e.g., wiring a real trust map).
    let _: std::marker::PhantomData<(Arc<()>, InMemoryIssuerTrustMap, TenantTrust)> =
        std::marker::PhantomData;
    Ok(())
}

/// Axum `from_fn`-compatible middleware. Runs once per request,
/// extracts the bearer, verifies via the global AuthGuard, and
/// inserts the `IdentityContext` into the request extensions for
/// downstream handlers + extractors to read.
///
/// On verification failure, returns an RFC 7807 problem response
/// with the `AuthError`'s status code and reason slug.
pub async fn auth_middleware(request: Request<Body>, next: Next) -> Result<Response, Response> {
    // Skip the predefined paths so probes work without auth.
    let path = request.uri().path();
    if EXCLUDED_PATHS.contains(&path) {
        return Ok(next.run(request).await);
    }

    let Some(guard) = AUTH_GUARD.get() else {
        // init_auth() wasn't called — fail closed. This is a
        // configuration error, not an auth failure; surface as 503.
        return Err(problem_response(
            StatusCode::SERVICE_UNAVAILABLE,
            "service_misconfigured",
            "AuthGuard not initialized; call init_auth() in main() before starting the server",
            None,
        ));
    };

    let token = match extract_bearer(&request) {
        Ok(t) => t,
        Err(err) => return Err(map_auth_error(&err)),
    };

    let identity = match guard.verify(&token).await {
        Ok(id) => id,
        Err(err) => return Err(map_auth_error(&err)),
    };

    // Convert the SDK's IdentityContext to the consumer's local type
    // before stashing in request extensions. Handlers in the base
    // service template extract ``&crate::identity::IdentityContext``;
    // inserting the SDK's nominal type would leave them looking up a
    // different ``TypeId`` from the same extension map. The two shapes
    // are field-by-field aligned by design.
    // SDK uses ``HashSet<String>`` for scopes/roles (set semantics for
    // wildcard scope-match). The local type uses ``Vec<String>`` for
    // ergonomic iteration order in handler code. Collect once at the
    // boundary so neither side has to convert per-access.
    let local = crate::identity::IdentityContext {
        tenant_id: identity.tenant_id,
        tenant_slug: identity.tenant_slug.clone(),
        subject: identity.subject.clone(),
        scopes: identity.scopes.iter().cloned().collect(),
        roles: identity.roles.iter().cloned().collect(),
        actor: identity.actor.clone(),
    };

    let mut request = request;
    request.extensions_mut().insert(local);
    Ok(next.run(request).await)
}

fn extract_bearer(request: &Request<Body>) -> Result<String, AuthError> {
    let value = request
        .headers()
        .get(header::AUTHORIZATION)
        .ok_or_else(|| AuthError::InvalidToken("missing Authorization header".into()))?;
    let raw = value
        .to_str()
        .map_err(|_| AuthError::InvalidToken("Authorization header is not valid UTF-8".into()))?;
    let (prefix, token) = raw.split_once(' ').ok_or_else(|| {
        AuthError::InvalidToken("Authorization header is not a Bearer token".into())
    })?;
    if !prefix.eq_ignore_ascii_case("bearer") || token.is_empty() {
        return Err(AuthError::InvalidToken(
            "Authorization header is not a Bearer token".into(),
        ));
    }
    Ok(token.trim().to_string())
}

fn map_auth_error(err: &AuthError) -> Response {
    let status =
        StatusCode::from_u16(err.status_code()).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let mut response = problem_response(status, err.reason(), &err.to_string(), None);
    if status == StatusCode::UNAUTHORIZED {
        response
            .headers_mut()
            .insert(header::WWW_AUTHENTICATE, "Bearer".parse().unwrap());
    }
    response
}

/// Build an RFC 7807 problem-response body. The shape matches the
/// Node plugin's response so cross-language clients dispatch on the
/// same `type` URI prefix.
fn problem_response(
    status: StatusCode,
    reason: &str,
    detail: &str,
    extra: Option<serde_json::Value>,
) -> Response {
    let mut body = json!({
        "type": format!("https://forge.dev/errors/{reason}"),
        "title": reason,
        "status": status.as_u16(),
        "detail": detail,
    });
    if let Some(extra_value) = extra {
        if let Some(map) = body.as_object_mut() {
            if let Some(extra_obj) = extra_value.as_object() {
                for (k, v) in extra_obj {
                    map.insert(k.clone(), v.clone());
                }
            }
        }
    }
    let mut response = Json(body).into_response();
    *response.status_mut() = status;
    response
}
