//! Cross-SDK parity runner for the Rust SDK.
//!
//! Loads the canonical scenario spec produced by Python's
//! `tests/contract/auth_sdk_parity/scenarios.py::scenarios_as_json()`,
//! mints a JWT for each scenario via the SDK's testing helper, runs
//! `AuthGuard::verify`, and asserts the outcome matches the expected
//! shape from the spec.
//!
//! Path semantics:
//!   - The forge test orchestrator (Python) writes the JSON dump to
//!     a tempfile and passes the path via `PARITY_FIXTURES` env var.
//!   - When the env var is unset, this test is a no-op so plain
//!     `cargo test --features testing` passes without the orchestrator.
//!
//! Cross-language parity contract:
//!   - Same JWT inputs (each scenario's mint config) must yield the
//!     same `IdentityContext` (or matching `AuthError` reason slug)
//!     across Python, Node, and Rust.
//!   - The `reason()` slugs are the cross-language client-dispatch
//!     contract — pinned in `errors.rs` and asserted here against
//!     each scenario's `expected.error` literal.
//!
//! ```bash
//! cd <project>/sdks/platform-auth-rs
//! PARITY_FIXTURES=/tmp/scenarios.json cargo test --features testing --test parity_runner
//! ```

#![cfg(feature = "testing")]

use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use jsonwebtoken::{Algorithm, EncodingKey, Header};
use platform_auth::{
    AuthGuard, AuthGuardConfig, InMemoryIssuerTrustMap, InMemoryRevocationStore, JwksCache,
    StaticMayActPolicy, TenantTrust,
    testing::{build_test_token, BuildTestTokenOptions, TestEcdsaKeypair},
};
use serde::Deserialize;
use serde_json::Value;
use uuid::Uuid;
use wiremock::{matchers, Mock, MockServer, ResponseTemplate};

// ---------------------------------------------------------------- spec types

#[derive(Deserialize, Debug, Clone)]
struct ExpectedOutcome {
    identity: Option<ExpectedIdentity>,
    error: Option<String>,
    error_message_contains: Option<String>,
}

#[derive(Deserialize, Debug, Clone)]
struct ExpectedIdentity {
    tenant_id: String,
    subject: String,
    #[serde(default)]
    roles: Vec<String>,
    #[serde(default)]
    scopes: Vec<String>,
    #[serde(default)]
    actor: Option<String>,
    #[serde(default)]
    tenant_slug: Option<String>,
    #[serde(default)]
    is_platform_admin: Option<bool>,
}

#[derive(Deserialize, Debug, Clone)]
#[serde(untagged)]
enum AudienceField {
    One(String),
    Many(Vec<String>),
}

impl AudienceField {
    fn as_vec(&self) -> Vec<String> {
        match self {
            Self::One(s) => vec![s.clone()],
            Self::Many(v) => v.clone(),
        }
    }
}

#[derive(Deserialize, Debug, Clone)]
struct TrustOverride {
    expected_issuer: String,
    #[serde(default)]
    suspended: bool,
}

#[derive(Deserialize, Debug, Clone)]
struct Scenario {
    name: String,
    #[allow(dead_code)]
    description: String,
    issuer: String,
    audience: AudienceField,
    subject: String,
    tenant_id: String,
    tenant_id_claim: String,
    #[serde(default)]
    tenant_slug: Option<String>,
    tenant_slug_claim: String,
    roles_claim: String,
    scope_claim: String,
    #[serde(default)]
    roles: Vec<String>,
    #[serde(default)]
    scopes: Vec<String>,
    ttl_seconds: u64,
    #[serde(default)]
    expires_at: Option<i64>,
    #[serde(default)]
    issued_at: Option<i64>,
    #[serde(default)]
    jti: Option<String>,
    algorithm: String,
    #[serde(default)]
    act: Option<Value>,
    #[serde(default)]
    extra_claims: HashMap<String, Value>,
    #[serde(default)]
    omit_claims: Vec<String>,
    verifier_audience: AudienceField,
    verifier_algorithms: Vec<String>,
    verifier_tenant_id_claim: String,
    verifier_roles_claim: String,
    verifier_scope_claim: String,
    verifier_tenant_slug_claim: String,
    #[serde(default)]
    revocation_denylist: Vec<String>,
    #[serde(default)]
    trust_map_overrides: HashMap<String, TrustOverride>,
    #[serde(default)]
    may_act_allowlist: HashMap<String, Vec<String>>,
    expected: ExpectedOutcome,
}

// Canonical issuer URL — must match scenarios.py's ISSUER constant.
const SPEC_ISSUER: &str = "http://gatekeeper.test:5000";

// ---------------------------------------------------------------- runner

#[tokio::test]
async fn cross_sdk_parity_rust() {
    let Ok(fixtures_path) = std::env::var("PARITY_FIXTURES") else {
        eprintln!("PARITY_FIXTURES not set — skipping cross-SDK parity runner");
        return;
    };
    let raw = std::fs::read_to_string(&fixtures_path)
        .unwrap_or_else(|e| panic!("read scenarios at {fixtures_path}: {e}"));
    let scenarios: Vec<Scenario> =
        serde_json::from_str(&raw).expect("parse scenarios JSON dump");

    let mut failed: Vec<(String, String)> = Vec::new();
    for scenario in &scenarios {
        match run_scenario(scenario).await {
            Ok(()) => {
                println!("✓ {}", scenario.name);
            }
            Err(reason) => {
                println!("✗ {}: {reason}", scenario.name);
                failed.push((scenario.name.clone(), reason));
            }
        }
    }

    if !failed.is_empty() {
        let summary = failed
            .iter()
            .map(|(n, r)| format!("  - {n}: {r}"))
            .collect::<Vec<_>>()
            .join("\n");
        panic!(
            "{} of {} scenarios failed:\n{summary}",
            failed.len(),
            scenarios.len()
        );
    }
}

async fn run_scenario(scenario: &Scenario) -> Result<(), String> {
    // Fresh keypair per scenario so test order doesn't matter.
    let keypair = TestEcdsaKeypair::generate()
        .map_err(|e| format!("generate keypair: {e}"))?;

    // Stand up wiremock to serve the JWKS at <mock>/auth/jwks. Map
    // the canonical SPEC_ISSUER to the mock's URL via JwksCache's
    // register_issuer (issuer `iss` claim stays the spec value;
    // only the JWKS-fetch URL points at wiremock).
    let mock_server = MockServer::start().await;
    let jwks_doc = keypair
        .jwks()
        .map_err(|e| format!("build JWKS doc: {e}"))?;
    Mock::given(matchers::method("GET"))
        .and(matchers::path("/auth/jwks"))
        .respond_with(ResponseTemplate::new(200).set_body_json(jwks_doc))
        .mount(&mock_server)
        .await;

    // Build verifier-side config from the scenario.
    let jwks = Arc::new(JwksCache::default().map_err(|e| format!("jwks init: {e}"))?);
    jwks.register_issuer(SPEC_ISSUER.to_string(), format!("{}/auth/jwks", mock_server.uri()))
        .await
        .map_err(|e| format!("register issuer: {e}"))?;

    let mut config = AuthGuardConfig::new(
        scenario
            .verifier_audience
            .as_vec()
            .into_iter()
            .next()
            .unwrap_or_else(|| "svc-test".into()),
        jwks,
    );
    config.audiences = scenario.verifier_audience.as_vec();
    config.algorithms = parse_algorithms(&scenario.verifier_algorithms)?;
    config.tenant_id_claim = scenario.verifier_tenant_id_claim.clone();
    config.tenant_slug_claim = scenario.verifier_tenant_slug_claim.clone();
    config.roles_claim = scenario.verifier_roles_claim.clone();
    config.scope_claim = scenario.verifier_scope_claim.clone();

    // Trust map — scenario opt-in only.
    if !scenario.trust_map_overrides.is_empty() {
        let map = build_trust_map(&scenario.trust_map_overrides)?;
        config.trust_map = Some(Arc::new(map));
    }

    // MayActPolicy — the spec is keyed actor → audiences (intuitive),
    // but the SDK is keyed audience → actors (deny-by-default at
    // the audience boundary). Invert here so the lookup keying
    // matches.
    if !scenario.may_act_allowlist.is_empty() {
        let mut inverted: HashMap<String, HashSet<String>> = HashMap::new();
        for (actor, audiences) in &scenario.may_act_allowlist {
            for audience in audiences {
                inverted
                    .entry(audience.clone())
                    .or_default()
                    .insert(actor.clone());
            }
        }
        config.may_act = Some(Arc::new(StaticMayActPolicy::new(
            inverted.into_iter().map(|(k, v)| (k, v.into_iter().collect::<Vec<_>>())),
        )));
    }

    if !scenario.revocation_denylist.is_empty() {
        config.revocation = Some(Arc::new(InMemoryRevocationStore::with_initial(
            scenario.revocation_denylist.iter().cloned(),
        )));
    }

    let auth_guard = AuthGuard::new(config).map_err(|e| format!("AuthGuard::new: {e}"))?;

    // Mint the token from the scenario's inputs.
    let token = mint_token(scenario, &keypair)?;

    // Verify.
    let result = auth_guard.verify(&token).await;

    match (&scenario.expected.identity, &scenario.expected.error) {
        (Some(expected), None) => {
            // Success path.
            let identity = result.map_err(|e| format!("expected success, got {e}"))?;
            if Uuid::parse_str(&expected.tenant_id)
                .map_err(|e| format!("expected.tenant_id not a UUID: {e}"))?
                != identity.tenant_id
            {
                return Err(format!(
                    "tenant_id mismatch: expected {} got {}",
                    expected.tenant_id, identity.tenant_id
                ));
            }
            if identity.subject != expected.subject {
                return Err(format!(
                    "subject mismatch: expected {} got {}",
                    expected.subject, identity.subject
                ));
            }
            if !sets_equal(&identity.roles, &expected.roles) {
                return Err(format!(
                    "roles mismatch: expected {:?} got {:?}",
                    expected.roles, identity.roles
                ));
            }
            if !sets_equal(&identity.scopes, &expected.scopes) {
                return Err(format!(
                    "scopes mismatch: expected {:?} got {:?}",
                    expected.scopes, identity.scopes
                ));
            }
            if identity.actor != expected.actor {
                return Err(format!(
                    "actor mismatch: expected {:?} got {:?}",
                    expected.actor, identity.actor
                ));
            }
            // Optional tenant_slug — assert when the scenario pins it;
            // a `None` expected.tenant_slug means "any value is fine"
            // (back-compat for scenarios written before the field
            // shipped). The dataclass field-name on the expected
            // identity is `tenant_slug` (snake_case across all 3 SDKs).
            if let Some(want_slug) = &expected.tenant_slug {
                if identity.tenant_slug.as_deref() != Some(want_slug.as_str()) {
                    return Err(format!(
                        "tenant_slug mismatch: expected {:?} got {:?}",
                        want_slug, identity.tenant_slug
                    ));
                }
            }
            if let Some(want_admin) = expected.is_platform_admin {
                if identity.is_platform_admin() != want_admin {
                    return Err(format!(
                        "is_platform_admin mismatch: expected {want_admin} got {}",
                        identity.is_platform_admin()
                    ));
                }
            }
            Ok(())
        }
        (None, Some(expected_slug)) => {
            // Failure path.
            let err = result.err().ok_or_else(|| {
                format!("expected error {expected_slug:?} but verify succeeded")
            })?;
            if err.reason() != expected_slug {
                return Err(format!(
                    "reason slug mismatch: expected {expected_slug:?} got {:?}",
                    err.reason()
                ));
            }
            if let Some(needle) = &scenario.expected.error_message_contains {
                let message = err.to_string().to_lowercase();
                if !message.contains(&needle.to_lowercase()) {
                    return Err(format!(
                        "error message {message:?} doesn't contain {needle:?}"
                    ));
                }
            }
            Ok(())
        }
        _ => Err("expected outcome must declare exactly one of identity/error".into()),
    }
}

// ---------------------------------------------------------------- helpers

fn parse_algorithms(specs: &[String]) -> Result<Vec<Algorithm>, String> {
    specs
        .iter()
        .map(|s| match s.as_str() {
            "ES256" => Ok(Algorithm::ES256),
            "ES384" => Ok(Algorithm::ES384),
            "RS256" => Ok(Algorithm::RS256),
            "HS256" => Ok(Algorithm::HS256),
            other => Err(format!("unsupported verifier algorithm: {other}")),
        })
        .collect()
}

fn build_trust_map(
    overrides: &HashMap<String, TrustOverride>,
) -> Result<InMemoryIssuerTrustMap, String> {
    let entries = overrides.iter().map(|(tenant_id, record)| {
        (
            tenant_id.clone(),
            TenantTrust {
                expected_issuer: record.expected_issuer.clone(),
                suspended: record.suspended,
            },
        )
    });
    Ok(InMemoryIssuerTrustMap::with_tenants(entries))
}

fn sets_equal(actual: &HashSet<String>, expected: &[String]) -> bool {
    let want: HashSet<&str> = expected.iter().map(String::as_str).collect();
    let got: HashSet<&str> = actual.iter().map(String::as_str).collect();
    want == got
}

fn mint_token(scenario: &Scenario, keypair: &TestEcdsaKeypair) -> Result<String, String> {
    // Negative-test paths that build_test_token can't produce —
    // hand-craft so the verifier's alg-allowlist or missing-kid
    // check fires before the signature step.
    if scenario.algorithm == "none" || scenario.algorithm == "HS256" {
        return Ok(craft_unsigned_or_hs(scenario, keypair));
    }
    if scenario.omit_claims.iter().any(|c| c == "kid") {
        return Ok(craft_unsigned_or_hs(scenario, keypair));
    }
    if scenario.omit_claims.iter().any(|c| c == &scenario.tenant_id_claim) {
        // Mint without the tenant claim — sign manually with the
        // SDK's keypair to avoid threading "omit" through the helper.
        return craft_signed_omitting_tenant(scenario, keypair);
    }

    let mut opts = BuildTestTokenOptions::new(
        keypair,
        scenario.issuer.clone(),
        scenario.audience.as_vec().into_iter().next().unwrap_or_default(),
        scenario.subject.clone(),
        scenario.tenant_id.clone(),
    );
    opts.audience = scenario.audience.as_vec();
    opts.tenant_id_claim = scenario.tenant_id_claim.clone();
    opts.roles_claim = scenario.roles_claim.clone();
    opts.scope_claim = scenario.scope_claim.clone();
    opts.roles = scenario.roles.clone();
    opts.scopes = scenario.scopes.clone();
    opts.ttl_seconds = scenario.ttl_seconds;
    if let Some(offset) = scenario.expires_at {
        opts.expires_at = Some(now_unix() + offset);
    }
    if let Some(offset) = scenario.issued_at {
        opts.issued_at = Some(now_unix() + offset);
    }
    if let Some(jti) = &scenario.jti {
        opts.jti = Some(jti.clone());
    }
    if let Some(act) = &scenario.act {
        opts.act = Some(act.clone());
    }
    opts.extra_claims = scenario.extra_claims.clone();
    // Mint the optional tenant_slug via extra_claims since
    // BuildTestTokenOptions doesn't expose a dedicated field — same
    // strategy as the Node runner.
    if let Some(slug) = &scenario.tenant_slug {
        opts.extra_claims.insert(
            scenario.tenant_slug_claim.clone(),
            Value::String(slug.clone()),
        );
    }
    build_test_token(opts).map_err(|e| format!("build_test_token: {e}"))
}

fn craft_unsigned_or_hs(scenario: &Scenario, keypair: &TestEcdsaKeypair) -> String {
    let now = now_unix();
    let issued_at = now + scenario.issued_at.unwrap_or(0);
    let expires_at = scenario
        .expires_at
        .map(|o| now + o)
        .unwrap_or_else(|| issued_at + scenario.ttl_seconds as i64);

    let mut header_map = serde_json::Map::new();
    header_map.insert("alg".into(), Value::String(scenario.algorithm.clone()));
    if !scenario.omit_claims.iter().any(|c| c == "kid") {
        header_map.insert("kid".into(), Value::String(keypair.kid.clone()));
    }
    let mut payload_map = serde_json::Map::new();
    payload_map.insert("iss".into(), Value::String(scenario.issuer.clone()));
    let aud_vec = scenario.audience.as_vec();
    payload_map.insert(
        "aud".into(),
        if aud_vec.len() == 1 {
            Value::String(aud_vec[0].clone())
        } else {
            Value::Array(aud_vec.into_iter().map(Value::String).collect())
        },
    );
    payload_map.insert("sub".into(), Value::String(scenario.subject.clone()));
    payload_map.insert("iat".into(), Value::Number(issued_at.into()));
    payload_map.insert("exp".into(), Value::Number(expires_at.into()));
    payload_map.insert(
        "jti".into(),
        Value::String(scenario.jti.clone().unwrap_or_else(|| {
            format!("test-jti-{:x}", (now as u64) ^ 0xdead_beef)
        })),
    );
    payload_map.insert(
        scenario.tenant_id_claim.clone(),
        Value::String(scenario.tenant_id.clone()),
    );
    if !scenario.roles.is_empty() {
        payload_map.insert(
            scenario.roles_claim.clone(),
            Value::Array(scenario.roles.iter().cloned().map(Value::String).collect()),
        );
    }
    if !scenario.scopes.is_empty() {
        payload_map.insert(
            scenario.scope_claim.clone(),
            Value::String(scenario.scopes.join(" ")),
        );
    }
    if let Some(act) = &scenario.act {
        payload_map.insert("act".into(), act.clone());
    }
    for (k, v) in &scenario.extra_claims {
        payload_map.insert(k.clone(), v.clone());
    }

    let header_b64 = URL_SAFE_NO_PAD.encode(serde_json::to_string(&header_map).unwrap());
    let payload_b64 = URL_SAFE_NO_PAD.encode(serde_json::to_string(&payload_map).unwrap());
    // Empty signature segment — the verifier rejects on alg
    // allowlist before the signature check, so the empty sig is
    // never inspected.
    format!("{header_b64}.{payload_b64}.")
}

fn craft_signed_omitting_tenant(
    scenario: &Scenario,
    keypair: &TestEcdsaKeypair,
) -> Result<String, String> {
    let now = now_unix();
    let issued_at = now + scenario.issued_at.unwrap_or(0);
    let expires_at = scenario
        .expires_at
        .map(|o| now + o)
        .unwrap_or_else(|| issued_at + scenario.ttl_seconds as i64);

    let mut payload = serde_json::Map::new();
    payload.insert("iss".into(), Value::String(scenario.issuer.clone()));
    let aud_vec = scenario.audience.as_vec();
    payload.insert(
        "aud".into(),
        if aud_vec.len() == 1 {
            Value::String(aud_vec[0].clone())
        } else {
            Value::Array(aud_vec.into_iter().map(Value::String).collect())
        },
    );
    payload.insert("sub".into(), Value::String(scenario.subject.clone()));
    payload.insert("iat".into(), Value::Number(issued_at.into()));
    payload.insert("exp".into(), Value::Number(expires_at.into()));
    payload.insert(
        "jti".into(),
        Value::String(scenario.jti.clone().unwrap_or_else(|| {
            format!("test-jti-{:x}", (now as u64) ^ 0xfeed_face)
        })),
    );
    // INTENTIONALLY NOT inserting tenant_id_claim — that's the
    // negative-test scenario's whole point.
    if !scenario.roles.is_empty() {
        payload.insert(
            scenario.roles_claim.clone(),
            Value::Array(scenario.roles.iter().cloned().map(Value::String).collect()),
        );
    }
    if !scenario.scopes.is_empty() {
        payload.insert(
            scenario.scope_claim.clone(),
            Value::String(scenario.scopes.join(" ")),
        );
    }
    if let Some(act) = &scenario.act {
        payload.insert("act".into(), act.clone());
    }
    for (k, v) in &scenario.extra_claims {
        payload.insert(k.clone(), v.clone());
    }

    let mut header = Header::new(Algorithm::ES256);
    header.kid = Some(keypair.kid.clone());
    let encoding_key = EncodingKey::from_ec_pem(keypair.private_pem.as_bytes())
        .map_err(|e| format!("EncodingKey::from_ec_pem: {e}"))?;
    jsonwebtoken::encode(&header, &Value::Object(payload), &encoding_key)
        .map_err(|e| format!("encode: {e}"))
}

fn now_unix() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}
