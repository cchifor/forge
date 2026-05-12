//! Integration test for the per-decision audit callback.
//!
//! Mirrors the behavioural contract pinned in Python's
//! `tests/unit/test_audit_callback.py` and Node's
//! `test/audit_callback.test.ts`: the callback fires once per
//! verified token, the record carries the cross-language fields
//! (`decision`, `audience`, `tenant_id`, `subject`, `actor`,
//! sorted `scopes`, `jti`, `iss`), and a missing callback is a
//! no-op (no panic, no allocation beyond the verifier's own).
//!
//! Gated on `testing` only — no axum needed (the audit callback is
//! framework-agnostic). Default features alone don't compile this.

#![cfg(feature = "testing")]

use std::sync::{Arc, Mutex};

use platform_auth::{
    testing::{build_test_token, BuildTestTokenOptions, TestEcdsaKeypair},
    AuthAuditRecord, AuthDecision, AuthGuard, AuthGuardConfig, JwksCache,
};
use wiremock::{matchers, Mock, MockServer, ResponseTemplate};

const TEST_ISSUER: &str = "http://gatekeeper.test:5000";
const TEST_AUDIENCE: &str = "svc-test";
const TEST_TENANT_ID: &str = "11111111-1111-4111-8111-111111111111";
const TEST_SUBJECT: &str = "22222222-2222-4222-8222-222222222222";

async fn setup() -> (Arc<JwksCache>, TestEcdsaKeypair, MockServer) {
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

    (jwks, keypair, mock)
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

#[tokio::test]
async fn audit_callback_fires_with_full_record_on_allow() {
    let (jwks, keypair, _mock) = setup().await;
    let captured: Arc<Mutex<Vec<AuthAuditRecord>>> = Arc::new(Mutex::new(Vec::new()));
    let captured_for_cb = captured.clone();
    let callback = Arc::new(move |record: AuthAuditRecord| {
        captured_for_cb.lock().unwrap().push(record);
    });

    let mut config = AuthGuardConfig::new(TEST_AUDIENCE, jwks);
    config.audit = Some(callback);
    let guard = AuthGuard::new(config).expect("guard");

    let token = mint_token(&keypair, &["things:read", "things:write"]);
    let _identity = guard.verify(&token).await.expect("verify");

    let records = captured.lock().unwrap();
    assert_eq!(records.len(), 1, "callback fires exactly once per allow");
    let record = &records[0];

    assert_eq!(record.decision, AuthDecision::Allow);
    assert_eq!(record.decision.as_str(), "allow");
    assert_eq!(record.audience, TEST_AUDIENCE);
    assert_eq!(record.audiences, vec![TEST_AUDIENCE.to_string()]);
    assert!(record.ts_unix > 0.0, "ts_unix must be unix-epoch seconds");
    assert_eq!(record.tenant_id.as_deref(), Some(TEST_TENANT_ID));
    assert_eq!(record.subject.as_deref(), Some(TEST_SUBJECT));
    assert_eq!(record.actor, None, "no act chain → actor is None");
    assert_eq!(
        record.tenant_slug, None,
        "no tenant_slug claim minted → record.tenant_slug is None"
    );
    // Cross-language sort guarantee: same scope set → same vec order.
    assert_eq!(
        record.scopes,
        Some(vec!["things:read".to_string(), "things:write".to_string()])
    );
    assert!(record.jti.is_some(), "jti must be populated on allow");
    assert_eq!(record.iss.as_deref(), Some(TEST_ISSUER));
    assert_eq!(record.reason, None, "reason is reserved for deny path");
}

#[tokio::test]
async fn audit_callback_propagates_tenant_slug() {
    let (jwks, keypair, _mock) = setup().await;
    let captured: Arc<Mutex<Vec<AuthAuditRecord>>> = Arc::new(Mutex::new(Vec::new()));
    let captured_for_cb = captured.clone();
    let callback = Arc::new(move |record: AuthAuditRecord| {
        captured_for_cb.lock().unwrap().push(record);
    });

    let mut config = AuthGuardConfig::new(TEST_AUDIENCE, jwks);
    config.audit = Some(callback);
    let guard = AuthGuard::new(config).expect("guard");

    // Mint with the default tenant_slug claim populated.
    let mut opts = BuildTestTokenOptions::new(
        &keypair,
        TEST_ISSUER,
        TEST_AUDIENCE,
        TEST_SUBJECT,
        TEST_TENANT_ID,
    );
    opts.extra_claims.insert(
        "https://forge/tenant_slug".to_string(),
        serde_json::Value::String("acme-corp".to_string()),
    );
    let token = build_test_token(opts).expect("mint token");

    let _identity = guard.verify(&token).await.expect("verify");

    let records = captured.lock().unwrap();
    assert_eq!(records.len(), 1);
    assert_eq!(
        records[0].tenant_slug.as_deref(),
        Some("acme-corp"),
        "tenant_slug from IdentityContext must surface in audit record"
    );
}

#[tokio::test]
async fn audit_callback_no_op_when_unset() {
    let (jwks, keypair, _mock) = setup().await;
    let config = AuthGuardConfig::new(TEST_AUDIENCE, jwks);
    let guard = AuthGuard::new(config).expect("guard");

    let token = mint_token(&keypair, &["things:read"]);
    // Just asserting the verify path doesn't panic when audit=None.
    let _ = guard.verify(&token).await.expect("verify");
}

#[tokio::test]
async fn audit_callback_does_not_fire_on_deny() {
    // Today the deny path is *not* wired for any of the three SDKs —
    // Python and Node only emit on allow, and Rust matches. This
    // test pins that current behavior so a future change to fire
    // on deny lands across all three SDKs in lockstep instead of
    // drifting one ahead.
    let (jwks, keypair, _mock) = setup().await;
    let captured: Arc<Mutex<Vec<AuthAuditRecord>>> = Arc::new(Mutex::new(Vec::new()));
    let captured_for_cb = captured.clone();
    let callback = Arc::new(move |record: AuthAuditRecord| {
        captured_for_cb.lock().unwrap().push(record);
    });

    let mut config = AuthGuardConfig::new("wrong-audience", jwks);
    config.audit = Some(callback);
    let guard = AuthGuard::new(config).expect("guard");

    // Token's `aud` is "svc-test" but verifier accepts only "wrong-audience".
    let token = mint_token(&keypair, &[]);
    let result = guard.verify(&token).await;
    assert!(result.is_err(), "audience mismatch must reject");

    let records = captured.lock().unwrap();
    assert!(
        records.is_empty(),
        "deny path is currently a no-op for cross-SDK parity (see audit.rs module docs)"
    );
}

#[tokio::test]
async fn audit_callback_records_actor_for_act_chain() {
    let (jwks, keypair, _mock) = setup().await;
    let captured: Arc<Mutex<Vec<AuthAuditRecord>>> = Arc::new(Mutex::new(Vec::new()));
    let captured_for_cb = captured.clone();
    let callback = Arc::new(move |record: AuthAuditRecord| {
        captured_for_cb.lock().unwrap().push(record);
    });

    let mut config = AuthGuardConfig::new(TEST_AUDIENCE, jwks);
    config.audit = Some(callback);
    let guard = AuthGuard::new(config).expect("guard");

    // Mint with an `act` claim — the verifier resolves the immediate
    // actor and the record should carry it.
    let mut opts = BuildTestTokenOptions::new(
        &keypair,
        TEST_ISSUER,
        TEST_AUDIENCE,
        TEST_SUBJECT,
        TEST_TENANT_ID,
    );
    opts.act = Some(serde_json::json!({"client_id": "svc-workflow"}));
    let token = build_test_token(opts).expect("mint token");

    let _identity = guard.verify(&token).await.expect("verify");

    let records = captured.lock().unwrap();
    assert_eq!(records.len(), 1);
    assert_eq!(
        records[0].actor.as_deref(),
        Some("svc-workflow"),
        "act-chain immediate-actor must surface in audit record"
    );
}
