//! Test-token minting helpers.
//!
//! Mirrors Python `platform_auth.testing` and Node `testing.ts`: lets
//! unit tests mint AuthGuard-verifiable JWTs without standing up a
//! real IdP. Exposes a tiny ECDSA P-256 keypair, a JWKS document
//! derived from it, and a `build_test_token` function that signs
//! arbitrary claims.
//!
//! Cross-language parity: same `BuildTestTokenOptions` invocation
//! (with the matching field names) must produce a token that all
//! three SDKs verify identically. The shared parity-fixture suite at
//! `forge/tests/contract/auth_sdk_parity/` pins this contract.
//!
//! Available behind no feature gate so production builds can also
//! mint a token if they need to (rare — typically for break-glass
//! tooling); the dev-dependencies that drive keypair generation
//! (`p256`, `ecdsa`, `rand`) keep this module's compile cost
//! contained.

use std::collections::HashMap;

use ecdsa::SigningKey;
use jsonwebtoken::{encode, Algorithm, EncodingKey, Header};
use p256::NistP256;
use rand::rngs::OsRng;
use serde::Serialize;
use serde_json::{json, Value};

use crate::errors::AuthError;

/// A test ECDSA P-256 keypair.
///
/// Holds both halves: the private key for signing test tokens and
/// the public key encoded as a PEM that callers feed to
/// `JwksCache::register_issuer` (or convert to JWK shape via
/// [`Self::public_jwk`]).
pub struct TestEcdsaKeypair {
    pub kid: String,
    /// PKCS8-PEM-encoded private key.
    pub private_pem: String,
    /// SPKI-PEM-encoded public key.
    pub public_pem: String,
}

impl TestEcdsaKeypair {
    /// Generate a fresh ES256 keypair. Slow (tens of ms) — cache per test.
    pub fn generate() -> Result<Self, AuthError> {
        Self::generate_with_kid(format!("test-key-{}", random_kid()))
    }

    pub fn generate_with_kid(kid: impl Into<String>) -> Result<Self, AuthError> {
        use p256::pkcs8::{EncodePrivateKey, EncodePublicKey};

        let signing_key: SigningKey<NistP256> = SigningKey::random(&mut OsRng);
        let private_pem = signing_key
            .to_pkcs8_pem(p256::pkcs8::LineEnding::LF)
            .map_err(|e| AuthError::InvalidToken(format!("private PEM encode: {e}")))?
            .to_string();
        let verifying_key = signing_key.verifying_key();
        let public_pem = verifying_key
            .to_public_key_pem(p256::pkcs8::LineEnding::LF)
            .map_err(|e| AuthError::InvalidToken(format!("public PEM encode: {e}")))?;
        Ok(Self {
            kid: kid.into(),
            private_pem,
            public_pem,
        })
    }

    /// Returns the public key as a JWK suitable for inclusion in a
    /// JWKS document. The JWK carries `kid`/`alg`/`use` so the
    /// resulting JWKS is directly usable by AuthGuard's verifier.
    pub fn public_jwk(&self) -> Result<Value, AuthError> {
        use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
        use p256::elliptic_curve::sec1::ToEncodedPoint;
        use p256::pkcs8::DecodePublicKey;

        let public_key = p256::PublicKey::from_public_key_pem(&self.public_pem)
            .map_err(|e| AuthError::InvalidToken(format!("public PEM decode: {e}")))?;
        let point = public_key.to_encoded_point(false);
        // Strip the SEC1 leading 0x04 (uncompressed point marker) and
        // split the remainder into the x/y coordinate halves.
        let bytes = point.as_bytes();
        // Compressed-point fast-path; we requested uncompressed above
        // so this should always have a leading 0x04 + 2*32 = 65 bytes.
        if bytes.len() != 65 || bytes[0] != 0x04 {
            return Err(AuthError::InvalidToken(
                "unexpected SEC1 encoding (not uncompressed P-256)".into(),
            ));
        }
        let x = URL_SAFE_NO_PAD.encode(&bytes[1..33]);
        let y = URL_SAFE_NO_PAD.encode(&bytes[33..65]);
        Ok(json!({
            "kty": "EC",
            "crv": "P-256",
            "x": x,
            "y": y,
            "kid": self.kid,
            "alg": "ES256",
            "use": "sig",
        }))
    }

    /// Returns a complete JWKS document containing only this
    /// keypair's public JWK. Drop into your test mock-server's
    /// response body for the JWKS endpoint.
    pub fn jwks(&self) -> Result<Value, AuthError> {
        Ok(json!({
            "keys": [self.public_jwk()?],
        }))
    }
}

/// Options for [`build_test_token`]. Defaults match the platform-auth
/// contract: 5-minute TTL, ES256, forge-namespaced tenant claim.
pub struct BuildTestTokenOptions<'a> {
    pub keypair: &'a TestEcdsaKeypair,
    pub issuer: String,
    pub audience: Vec<String>,
    pub subject: String,
    pub tenant_id: String,
    pub roles: Vec<String>,
    pub scopes: Vec<String>,
    pub tenant_id_claim: String,
    /// Plural to match `AuthGuardConfig::roles_claim`, the Python
    /// `roles_claim`, and the Node `rolesClaim`. The cross-language
    /// JWT claim defaults to `"roles"` (a JSON array of strings).
    pub roles_claim: String,
    pub scope_claim: String,
    pub ttl_seconds: u64,
    pub not_before_seconds: Option<i64>,
    pub expires_at: Option<i64>,
    pub issued_at: Option<i64>,
    /// RFC 8693 `act` claim — produces an on-behalf-of token.
    pub act: Option<Value>,
    pub jti: Option<String>,
    /// Override the JWT `alg` header (e.g., `Algorithm::HS256` for
    /// negative tests). Defaults to `ES256`.
    pub algorithm: Algorithm,
    /// Extra claims merged verbatim into the payload.
    pub extra_claims: HashMap<String, Value>,
}

impl<'a> BuildTestTokenOptions<'a> {
    /// Required-fields constructor. Defaults: ES256, 5-minute TTL,
    /// `https://forge/tenant_id`, `roles`, `scope`.
    pub fn new(
        keypair: &'a TestEcdsaKeypair,
        issuer: impl Into<String>,
        audience: impl Into<String>,
        subject: impl Into<String>,
        tenant_id: impl Into<String>,
    ) -> Self {
        Self {
            keypair,
            issuer: issuer.into(),
            audience: vec![audience.into()],
            subject: subject.into(),
            tenant_id: tenant_id.into(),
            roles: Vec::new(),
            scopes: Vec::new(),
            tenant_id_claim: "https://forge/tenant_id".to_string(),
            roles_claim: "roles".to_string(),
            scope_claim: "scope".to_string(),
            ttl_seconds: 300,
            not_before_seconds: None,
            expires_at: None,
            issued_at: None,
            act: None,
            jti: None,
            algorithm: Algorithm::ES256,
            extra_claims: HashMap::new(),
        }
    }
}

/// Mint a signed JWT with the given claims.
///
/// Use this from unit tests to feed AuthGuard a verifiable token
/// without needing a real Gatekeeper/Keycloak. The `algorithm`
/// option lets negative tests exercise the alg-allowlist (e.g.,
/// minting an HS256 token to confirm AuthGuard rejects it).
pub fn build_test_token(opts: BuildTestTokenOptions) -> Result<String, AuthError> {
    let now = chrono_now();
    let issued_at = opts.issued_at.unwrap_or(now);
    let expires_at = opts
        .expires_at
        .unwrap_or_else(|| issued_at + opts.ttl_seconds as i64);

    let mut payload = serde_json::Map::new();
    payload.insert("iss".to_string(), Value::String(opts.issuer));
    payload.insert(
        "aud".to_string(),
        if opts.audience.len() == 1 {
            Value::String(opts.audience[0].clone())
        } else {
            Value::Array(opts.audience.into_iter().map(Value::String).collect())
        },
    );
    payload.insert("sub".to_string(), Value::String(opts.subject));
    payload.insert("iat".to_string(), Value::Number(issued_at.into()));
    payload.insert("exp".to_string(), Value::Number(expires_at.into()));
    payload.insert(
        "jti".to_string(),
        Value::String(opts.jti.unwrap_or_else(random_jti)),
    );
    payload.insert(opts.tenant_id_claim, Value::String(opts.tenant_id));

    if let Some(nbf_offset) = opts.not_before_seconds {
        payload.insert(
            "nbf".to_string(),
            Value::Number((issued_at + nbf_offset).into()),
        );
    }
    if !opts.roles.is_empty() {
        payload.insert(
            opts.roles_claim,
            Value::Array(opts.roles.into_iter().map(Value::String).collect()),
        );
    }
    if !opts.scopes.is_empty() {
        payload.insert(opts.scope_claim, Value::String(opts.scopes.join(" ")));
    }
    if let Some(act) = opts.act {
        payload.insert("act".to_string(), act);
    }
    for (k, v) in opts.extra_claims {
        payload.insert(k, v);
    }

    let mut header = Header::new(opts.algorithm);
    header.kid = Some(opts.keypair.kid.clone());

    // Build the encoding key from the PEM. jsonwebtoken supports
    // EC PKCS8 PEMs for ES256 / ES384 directly.
    let encoding_key = if matches!(opts.algorithm, Algorithm::ES256 | Algorithm::ES384) {
        EncodingKey::from_ec_pem(opts.keypair.private_pem.as_bytes())
            .map_err(|e| AuthError::InvalidToken(format!("EC PEM decode: {e}")))?
    } else {
        // Negative-test path — caller wants a non-EC algorithm
        // (e.g., HS256). They must bring their own secret via
        // `extra_claims`-style overrides. Document as unsupported
        // and bail.
        return Err(AuthError::InvalidToken(format!(
            "build_test_token only supports ES256/ES384; got {:?}",
            opts.algorithm
        )));
    };

    encode(&header, &Value::Object(payload), &encoding_key)
        .map_err(|e| AuthError::InvalidToken(format!("encode failed: {e}")))
}

/// Convenience factory for the most common case — a freshly
/// generated keypair plus a token signed with default options.
pub fn fresh_keypair_and_token(
    issuer: impl Into<String>,
    audience: impl Into<String>,
    subject: impl Into<String>,
    tenant_id: impl Into<String>,
) -> Result<(TestEcdsaKeypair, String), AuthError> {
    let keypair = TestEcdsaKeypair::generate()?;
    let token = build_test_token(BuildTestTokenOptions::new(
        &keypair, issuer, audience, subject, tenant_id,
    ))?;
    Ok((keypair, token))
}

// ---------------------------------------------------------------- internals

#[derive(Serialize)]
#[allow(dead_code)] // for callers that want a typed shape
struct StandardClaims {
    iss: String,
    aud: Vec<String>,
    sub: String,
    iat: i64,
    exp: i64,
    jti: String,
}

/// Wall clock in seconds since the Unix epoch. Avoids pulling
/// in `chrono` just for this — `std::time::SystemTime` is enough.
fn chrono_now() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn random_jti() -> String {
    use rand::Rng;
    let n: u64 = rand::thread_rng().gen();
    format!("test-jti-{n:x}")
}

fn random_kid() -> String {
    use rand::Rng;
    let n: u64 = rand::thread_rng().gen();
    format!("{n:x}")
}
