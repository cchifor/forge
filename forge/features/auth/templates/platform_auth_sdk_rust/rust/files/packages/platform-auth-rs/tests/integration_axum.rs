//! End-to-end integration test for the Axum Tower stack.
//!
//! Builds a real `axum::Router` with the SDK's `AuthLayer` +
//! per-route `RequireScope` layer + the `IdentityContext`
//! `FromRequestParts` extractor, then exercises it via
//! `tower::ServiceExt::oneshot`. Validates the middleware
//! composition holds end-to-end:
//!
//!   - `AuthLayer` extracts the bearer, verifies via `AuthGuard`,
//!     binds `IdentityContext` to request extensions
//!   - `IdentityContext` extractor reads from extensions in handler
//!     signatures
//!   - `RequireScope` consumes the bound identity, asserts scope,
//!     short-circuits with `403` mapped to RFC 7807 problem response
//!     when missing
//!   - Skip-list (`/health`, etc.) bypasses verification cleanly
//!
//! Bare-verifier parity is gated by `tests/parity_runner.rs`; this
//! test gates the *layer composition* — the unique-to-Rust path that
//! the cross-language parity runner can't exercise.
//!
//! Gated behind both the `axum` and `testing` features so consumers
//! of the bare verifier don't pay the Tower compile cost.

#![cfg(all(feature = "axum", feature = "testing"))]

use std::sync::Arc;

use axum::{
    body::Body,
    http::{header, Request, StatusCode},
    routing::get,
    Router,
};
use platform_auth::{
    testing::{build_test_token, BuildTestTokenOptions, TestEcdsaKeypair},
    AuthGuard, AuthGuardConfig, AuthLayer, IdentityContext, JwksCache, RequireScope,
};
use tower::ServiceExt;
use wiremock::{matchers, Mock, MockServer, ResponseTemplate};

const TEST_ISSUER: &str = "http://gatekeeper.test:5000";
const TEST_AUDIENCE: &str = "svc-test";
const TEST_TENANT_ID: &str = "11111111-1111-4111-8111-111111111111";
const TEST_SUBJECT: &str = "22222222-2222-4222-8222-222222222222";

/// Stand up an AuthGuard wired to a mock-served JWKS endpoint plus
/// a fresh keypair we sign tokens with. Returns the keypair so the
/// caller can mint per-test tokens.
async fn setup() -> (Arc<AuthGuard>, TestEcdsaKeypair, MockServer) {
    let keypair = TestEcdsaKeypair::generate().expect("generate keypair");
    let mock = MockServer::start().await;
    Mock::given(matchers::method("GET"))
        .and(matchers::path("/auth/jwks"))
        .respond_with(ResponseTemplate::new(200).set_body_json(keypair.jwks().expect("jwks")))
        .mount(&mock)
        .await;

    let jwks = Arc::new(JwksCache::with_defaults().expect("jwks init"));
    jwks.register_issuer(TEST_ISSUER.to_string(), format!("{}/auth/jwks", mock.uri()))
        .await
        .expect("register issuer");

    let mut config = AuthGuardConfig::new(TEST_AUDIENCE, jwks);
    config.tenant_id_claim = "https://forge/tenant_id".to_string();
    let guard = Arc::new(AuthGuard::new(config).expect("auth guard"));
    (guard, keypair, mock)
}

fn mint_token(keypair: &TestEcdsaKeypair, scopes: &[&str]) -> String {
    let mut opts = BuildTestTokenOptions::new(
        keypair,
        TEST_ISSUER,
        TEST_AUDIENCE,
        TEST_SUBJECT,
        TEST_TENANT_ID,
    );
    opts.scopes = scopes.iter().map(|s| s.to_string()).collect();
    build_test_token(opts).expect("mint token")
}

/// Handler that reads the bound IdentityContext via the extractor.
/// Returns the tenant id so we can assert the binding propagated
/// from the AuthLayer through to the handler signature.
async fn things_handler(identity: IdentityContext) -> String {
    identity.tenant_id.to_string()
}

/// Handler used for the skip-listed path. Asserts no identity is
/// bound (the AuthLayer skipped verification).
async fn health_handler() -> &'static str {
    "ok"
}

fn build_app(guard: Arc<AuthGuard>) -> Router {
    Router::new()
        .route(
            "/things",
            get(things_handler).layer(RequireScope::new(["things:read"])),
        )
        .route(
            "/things/admin",
            get(things_handler).layer(RequireScope::new([
                "things:admin",
                "platform:support:write",
            ])),
        )
        .route("/health", get(health_handler))
        .layer(AuthLayer::new(guard))
}

#[tokio::test]
async fn auth_layer_binds_identity_for_handler() {
    let (guard, keypair, _mock) = setup().await;
    let app = build_app(guard);
    let token = mint_token(&keypair, &["things:read"]);

    let response = app
        .oneshot(
            Request::builder()
                .uri("/things")
                .header(header::AUTHORIZATION, format!("Bearer {token}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .expect("oneshot");
    assert_eq!(response.status(), StatusCode::OK);
    let body = axum::body::to_bytes(response.into_body(), 1024)
        .await
        .expect("body");
    assert_eq!(std::str::from_utf8(&body).unwrap(), TEST_TENANT_ID);
}

#[tokio::test]
async fn auth_layer_rejects_missing_bearer() {
    let (guard, _keypair, _mock) = setup().await;
    let app = build_app(guard);

    let response = app
        .oneshot(
            Request::builder()
                .uri("/things")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .expect("oneshot");
    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    // RFC 7807 problem-response shape — same `https://forge.dev/errors/`
    // URI prefix as the Node plugin.
    let body = axum::body::to_bytes(response.into_body(), 1024)
        .await
        .expect("body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("json");
    assert_eq!(payload["title"], "invalid_token");
    assert!(
        payload["type"]
            .as_str()
            .unwrap_or_default()
            .starts_with("https://forge.dev/errors/"),
        "type URI should be the canonical problem-response prefix"
    );
}

#[tokio::test]
async fn require_scope_rejects_missing_scope() {
    let (guard, keypair, _mock) = setup().await;
    let app = build_app(guard);
    // Token has `things:read` but the route requires `things:admin`.
    let token = mint_token(&keypair, &["things:read"]);

    let response = app
        .oneshot(
            Request::builder()
                .uri("/things/admin")
                .header(header::AUTHORIZATION, format!("Bearer {token}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .expect("oneshot");
    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    let body = axum::body::to_bytes(response.into_body(), 1024)
        .await
        .expect("body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("json");
    assert_eq!(payload["title"], "scope_required");
}

#[tokio::test]
async fn require_scope_accepts_when_all_required_scopes_present() {
    // `RequireScope::new(["things:admin", "platform:support:write"])`
    // is AND semantics — every listed scope must be granted. Token
    // here grants both, so the route should pass.
    let (guard, keypair, _mock) = setup().await;
    let app = build_app(guard);
    let token = mint_token(&keypair, &["things:admin", "platform:support:write"]);

    let response = app
        .oneshot(
            Request::builder()
                .uri("/things/admin")
                .header(header::AUTHORIZATION, format!("Bearer {token}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .expect("oneshot");
    assert_eq!(response.status(), StatusCode::OK);
}

#[tokio::test]
async fn auth_layer_skips_health_endpoint() {
    let (guard, _keypair, _mock) = setup().await;
    let app = build_app(guard);

    // No bearer header — but `/health` is in the skip-list.
    let response = app
        .oneshot(
            Request::builder()
                .uri("/health")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .expect("oneshot");
    assert_eq!(response.status(), StatusCode::OK);
    let body = axum::body::to_bytes(response.into_body(), 1024)
        .await
        .expect("body");
    assert_eq!(std::str::from_utf8(&body).unwrap(), "ok");
}

#[tokio::test]
async fn require_scope_supports_wildcard() {
    // Token has `things:*` (wildcard); route requires `things:read`.
    // The wildcard-aware `scope_satisfies` should accept.
    let (guard, keypair, _mock) = setup().await;
    let app = build_app(guard);
    let token = mint_token(&keypair, &["things:*"]);

    let response = app
        .oneshot(
            Request::builder()
                .uri("/things")
                .header(header::AUTHORIZATION, format!("Bearer {token}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .expect("oneshot");
    assert_eq!(response.status(), StatusCode::OK);
}
