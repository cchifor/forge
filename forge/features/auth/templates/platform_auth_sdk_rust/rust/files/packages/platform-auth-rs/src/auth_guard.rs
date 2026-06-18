//! AuthGuard — JWT bearer-token verifier.
//!
//! Mirrors Python `platform_auth.auth_guard.AuthGuard` and Node
//! `AuthGuard.ts`. On each request:
//!   1. Extract `Authorization: Bearer <jwt>` from the request.
//!   2. Reject any algorithm not in the configured allowlist.
//!   3. Read the unverified `iss` claim, look up the JWKS resolver.
//!   4. Verify signature + `aud` + `exp` + `nbf` + required claims.
//!   5. Resolve tenant claim, consult `IssuerTrustMap`.
//!   6. Consult `RevocationStore`.
//!   7. Walk RFC 8693 `act` chain, ask `MayActPolicy`.
//!   8. Build `IdentityContext`, return.
//!
//! A failure at any step returns a typed `AuthError`. The caller's
//! HTTP error mapper translates them to RFC 7807 responses via
//! `error.status_code()` and `error.reason()`.
//!
//! Construct once per process and reuse as a Tower layer extractor;
//! never per-request.

use std::{collections::HashSet, sync::Arc};

use jsonwebtoken::{decode, decode_header, Algorithm, Validation};
use serde_json::Value;
use uuid::Uuid;

use crate::{
    audit::{AuthAuditCallback, AuthAuditRecord, AuthDecision},
    errors::AuthError,
    identity::IdentityContext,
    jwks::JwksCache,
    may_act::MayActPolicy,
    revocation::RevocationStore,
    trust::IssuerTrustMap,
};

pub const DEFAULT_TENANT_ID_CLAIM: &str = "https://forge/tenant_id";
pub const DEFAULT_TENANT_SLUG_CLAIM: &str = "https://forge/tenant_slug";
pub const DEFAULT_ROLES_CLAIM: &str = "roles";
pub const DEFAULT_SCOPE_CLAIM: &str = "scope";

/// Claims jose must enforce as present (RFC 9068 §2.2).
/// `nbf` is intentionally absent: OPTIONAL per RFC 7519 §4.1.5.
pub const REQUIRED_CLAIMS: &[&str] = &["iss", "aud", "sub", "exp", "iat", "jti"];

/// Default accepted JWT signing algorithms. Asymmetric only — never
/// `none` or `HS*`. ES256 is the platform standard (smaller signatures,
/// ~10× faster signing than RS256).
pub fn default_algorithms() -> Vec<Algorithm> {
    vec![Algorithm::ES256]
}

pub const DEFAULT_CLOCK_SKEW_SECONDS: u64 = 30;
pub const ACT_CHAIN_MAX_DEPTH: usize = 10;

#[derive(Clone)]
pub struct AuthGuardConfig {
    /// At least one accepted audience. Token's `aud` claim matches any.
    pub audiences: Vec<String>,
    /// Required: multi-issuer JWKS cache.
    pub jwks: Arc<JwksCache>,
    /// Optional: per-tenant issuer trust map.
    pub trust_map: Option<Arc<dyn IssuerTrustMap>>,
    /// When `true`, a token whose tenant has no record in `trust_map` is
    /// rejected with `IssuerNotTrusted`. Default `false` — the permissive
    /// single-issuer default mirroring Python's
    /// `AuthGuard(strict_trust=False)`: per-tenant issuer binding +
    /// suspension only constrain tenants explicitly registered in the map,
    /// so a gatekeeper / oidc_generic deployment can ship an *empty* trust
    /// map without rejecting every token. Set `true` for hybrid-realm
    /// deployments where every tenant must be registered.
    pub strict_trust: bool,
    /// Optional: revoked-jti store.
    pub revocation: Option<Arc<dyn RevocationStore>>,
    /// Optional: RFC 8693 act-chain authorization policy.
    pub may_act: Option<Arc<dyn MayActPolicy>>,
    /// Allowed signing algorithms. Default `[ES256]`. `none` always rejected.
    pub algorithms: Vec<Algorithm>,
    /// Clock-skew leeway in seconds. Default 30.
    pub clock_skew_seconds: u64,
    /// JWT claim carrying the tenant UUID. Default `https://forge/tenant_id`.
    pub tenant_id_claim: String,
    /// Optional JWT claim carrying a human-readable tenant slug. Default
    /// `https://forge/tenant_slug`. The verifier reads it into
    /// `IdentityContext.tenant_slug` when present; absent claims yield
    /// `None`. Slugs are not validated against any registry — they're
    /// informational labels.
    pub tenant_slug_claim: String,
    /// JWT claim carrying realm roles. Default `roles`.
    pub roles_claim: String,
    /// JWT claim carrying space-separated OAuth scopes. Default `scope`.
    pub scope_claim: String,
    /// Optional per-decision audit callback. Mirrors Python's
    /// `AuthGuard(audit=...)` and Node's `AuthGuardConfig.audit`.
    /// Today fires only on the allow path — same as the canonical
    /// SDKs. See `audit.rs` for the record shape contract.
    pub audit: Option<AuthAuditCallback>,
}

impl AuthGuardConfig {
    /// Minimal config — single audience, default everything else.
    pub fn new(audience: impl Into<String>, jwks: Arc<JwksCache>) -> Self {
        Self {
            audiences: vec![audience.into()],
            jwks,
            trust_map: None,
            strict_trust: false,
            revocation: None,
            may_act: None,
            algorithms: default_algorithms(),
            clock_skew_seconds: DEFAULT_CLOCK_SKEW_SECONDS,
            tenant_id_claim: DEFAULT_TENANT_ID_CLAIM.into(),
            tenant_slug_claim: DEFAULT_TENANT_SLUG_CLAIM.into(),
            roles_claim: DEFAULT_ROLES_CLAIM.into(),
            scope_claim: DEFAULT_SCOPE_CLAIM.into(),
            audit: None,
        }
    }
}

pub struct AuthGuard {
    config: AuthGuardConfig,
}

impl AuthGuard {
    pub fn new(config: AuthGuardConfig) -> Result<Self, AuthError> {
        if config.audiences.is_empty() {
            return Err(AuthError::InvalidToken(
                "audiences must be non-empty".into(),
            ));
        }
        for entry in &config.audiences {
            if entry.is_empty() {
                return Err(AuthError::InvalidToken(
                    "audience entries must be non-empty".into(),
                ));
            }
        }
        if config.algorithms.is_empty() {
            return Err(AuthError::InvalidToken(
                "algorithms must be non-empty".into(),
            ));
        }
        // jsonwebtoken's Algorithm enum can't represent `none`; safe.
        if config.tenant_id_claim.is_empty() {
            return Err(AuthError::InvalidToken(
                "tenant_id_claim must be non-empty".into(),
            ));
        }
        Ok(Self { config })
    }

    /// Primary audience — singular for diagnostic/logging callers.
    pub fn audience(&self) -> &str {
        &self.config.audiences[0]
    }

    /// All accepted audiences.
    pub fn audiences(&self) -> &[String] {
        &self.config.audiences
    }

    /// Validate `token` and return the verified `IdentityContext`.
    ///
    /// Emits a `tracing` span (`platform_auth.verify`) covering the
    /// hot path. Service-side OpenTelemetry exporters that subscribe
    /// to the `tracing` ecosystem (via `tracing-opentelemetry` or
    /// `opentelemetry-tracing-subscriber`) automatically pick this
    /// up — every protected endpoint's trace tree has a child
    /// `verify` span without per-handler instrumentation. Mirrors
    /// the way Python's verifier emits an OpenTelemetry span via
    /// `opentelemetry.trace.get_tracer(...).start_as_current_span`
    /// inside `AuthGuard.verify`. On success the span records
    /// `tenant_id`, `subject`, `actor` (when present); on failure
    /// the span records the typed `reason()` slug and is marked as
    /// errored — same diagnostic surface as the Python and Node
    /// equivalents.
    #[tracing::instrument(
        name = "platform_auth.verify",
        skip(self, token),
        fields(
            audience = self.config.audiences.first().map(String::as_str).unwrap_or(""),
            tenant_id = tracing::field::Empty,
            subject = tracing::field::Empty,
            actor = tracing::field::Empty,
            reason = tracing::field::Empty,
        ),
    )]
    pub async fn verify(&self, token: &str) -> Result<IdentityContext, AuthError> {
        let result = self.verify_inner(token).await;
        let span = tracing::Span::current();
        match &result {
            Ok(identity) => {
                span.record("tenant_id", tracing::field::display(&identity.tenant_id));
                span.record("subject", tracing::field::display(&identity.subject));
                if let Some(actor) = &identity.actor {
                    span.record("actor", tracing::field::display(actor));
                }
            }
            Err(err) => {
                span.record("reason", tracing::field::display(err.reason()));
            }
        }
        result
    }

    async fn verify_inner(&self, token: &str) -> Result<IdentityContext, AuthError> {
        if token.is_empty() {
            return Err(AuthError::InvalidToken("missing bearer token".into()));
        }

        let header = decode_header(token).map_err(AuthError::from)?;
        if !self.config.algorithms.contains(&header.alg) {
            return Err(AuthError::InvalidToken(format!(
                "algorithm {:?} not allowed",
                header.alg
            )));
        }
        let kid = header
            .kid
            .as_ref()
            .ok_or_else(|| AuthError::InvalidToken("token header missing 'kid'".into()))?;

        // Decode the unverified payload to read `iss`. jsonwebtoken
        // doesn't expose a "decode without verifying" helper directly,
        // so we parse the middle segment manually. (It's just
        // base64url-encoded JSON.)
        let unverified = unverified_claims(token)?;
        let iss = unverified
            .get("iss")
            .and_then(|v| v.as_str())
            .ok_or_else(|| AuthError::InvalidToken("token missing 'iss'".into()))?;
        if !self.config.jwks.is_registered(iss).await {
            return Err(AuthError::InvalidToken(format!(
                "issuer {iss:?} is not registered"
            )));
        }

        let key = self.config.jwks.get_signing_key(iss, kid).await?;

        let mut validation = Validation::new(header.alg);
        validation.set_audience(&self.config.audiences);
        validation.set_required_spec_claims(REQUIRED_CLAIMS);
        validation.leeway = self.config.clock_skew_seconds;
        validation.algorithms = self.config.algorithms.clone();
        // jsonwebtoken's Validation defaults validate_nbf=false, so a future
        // `nbf` would otherwise be ignored. Python (PyJWT) and Node (jose)
        // both reject not-yet-valid tokens; enable nbf validation for parity
        // (the ImmatureSignature -> InvalidToken mapping in errors.rs is what
        // surfaces the `invalid_token` "token not yet valid" rejection).
        validation.validate_nbf = true;

        let token_data = decode::<Value>(token, &key, &validation).map_err(AuthError::from)?;
        let claims = token_data.claims;

        let tenant_id = self.extract_tenant_id(&claims)?;

        if let Some(trust_map) = &self.config.trust_map {
            self.enforce_trust(trust_map.as_ref(), &tenant_id, iss)
                .await?;
        }

        let jti = claims
            .get("jti")
            .and_then(|v| v.as_str())
            .ok_or_else(|| AuthError::InvalidToken("missing required claim: jti".into()))?
            .to_string();
        if let Some(revocation) = &self.config.revocation {
            if revocation.is_revoked(&jti).await {
                return Err(AuthError::TokenRevoked(format!(
                    "token jti {:?} is revoked",
                    jti
                )));
            }
        }

        let actor = self.enforce_act_chain(&claims)?;

        // Optional tenant slug — read from the configured claim if
        // present. Absent claim → `None`; non-string claim → `None`
        // (slugs are informational; we don't reject the token over a
        // malformed slug field).
        let tenant_slug = claims
            .get(&self.config.tenant_slug_claim)
            .and_then(|v| v.as_str())
            .map(String::from);

        let identity = IdentityContext {
            tenant_id,
            subject: claims
                .get("sub")
                .and_then(|v| v.as_str())
                .unwrap_or_default()
                .to_string(),
            roles: extract_string_set(&claims, &self.config.roles_claim, true)?,
            scopes: extract_string_set(&claims, &self.config.scope_claim, false)?,
            actor,
            tenant_slug,
            raw_claims: claims,
        };

        // Emit the audit record on the allow path. Mirrors Python's
        // `_emit_audit(decision="allow", identity=..., jti=..., iss=...)`
        // and Node's `_emitAudit({decision: "allow", ...})`.
        self.emit_audit(
            AuthDecision::Allow,
            Some(&identity),
            Some(&jti),
            Some(iss),
            None,
        );

        Ok(identity)
    }

    /// Build + dispatch an `AuthAuditRecord`. No-op when no callback
    /// is configured. Cross-language record shape pinned by `audit.rs`.
    fn emit_audit(
        &self,
        decision: AuthDecision,
        identity: Option<&IdentityContext>,
        jti: Option<&str>,
        iss: Option<&str>,
        reason: Option<&str>,
    ) {
        let Some(callback) = &self.config.audit else {
            return;
        };
        let ts_unix = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        let mut record = AuthAuditRecord {
            decision,
            audience: self.config.audiences[0].clone(),
            audiences: self.config.audiences.clone(),
            ts_unix,
            tenant_id: None,
            tenant_slug: None,
            subject: None,
            actor: None,
            scopes: None,
            jti: jti.map(String::from),
            iss: iss.map(String::from),
            reason: reason.map(String::from),
        };
        if let Some(id) = identity {
            record.tenant_id = Some(id.tenant_id.to_string());
            record.tenant_slug = id.tenant_slug.clone();
            record.subject = Some(id.subject.clone());
            record.actor = id.actor.clone();
            // Sort for cross-language byte-identical output (matches
            // Python's `sorted(...)` + Node's `[...scopes].sort()`).
            let mut scopes: Vec<String> = id.scopes.iter().cloned().collect();
            scopes.sort();
            record.scopes = Some(scopes);
        }
        callback(record);
    }

    fn extract_tenant_id(&self, claims: &Value) -> Result<Uuid, AuthError> {
        let raw = claims.get(&self.config.tenant_id_claim).ok_or_else(|| {
            AuthError::InvalidToken(format!(
                "missing tenant claim: {:?}",
                self.config.tenant_id_claim
            ))
        })?;
        let s = raw.as_str().ok_or_else(|| {
            AuthError::InvalidToken(format!(
                "tenant claim {:?} must be a UUID string",
                self.config.tenant_id_claim
            ))
        })?;
        Uuid::parse_str(s).map_err(|_| {
            AuthError::InvalidToken(format!(
                "tenant claim {:?} is not a valid UUID",
                self.config.tenant_id_claim
            ))
        })
    }

    async fn enforce_trust(
        &self,
        trust_map: &dyn IssuerTrustMap,
        tenant_id: &Uuid,
        iss: &str,
    ) -> Result<(), AuthError> {
        // A missing record means the tenant is unknown to the trust map.
        // Default (strict_trust=false): accept — the permissive single-issuer
        // default. Per-tenant issuer binding + suspension only apply to
        // tenants explicitly registered. This is what lets the gatekeeper /
        // oidc_generic providers ship an empty map without rejecting every
        // token. Matches Python's AuthGuard._enforce_trust.
        let record = match trust_map.get(&tenant_id.to_string()).await {
            Some(record) => record,
            None => {
                if self.config.strict_trust {
                    return Err(AuthError::IssuerNotTrusted(format!(
                        "tenant {} is not registered in the trust map (strict_trust is enabled)",
                        tenant_id
                    )));
                }
                return Ok(());
            }
        };
        if record.expected_issuer != iss {
            return Err(AuthError::IssuerNotTrusted(format!(
                "tenant {} expects issuer {:?}, token presents {:?}",
                tenant_id, record.expected_issuer, iss
            )));
        }
        if record.suspended {
            return Err(AuthError::TenantSuspended(format!(
                "tenant {} is suspended",
                tenant_id
            )));
        }
        Ok(())
    }

    fn enforce_act_chain(&self, claims: &Value) -> Result<Option<String>, AuthError> {
        let Some(act) = claims.get("act") else {
            return Ok(None);
        };
        if !act.is_object() {
            return Err(AuthError::InvalidToken(
                "'act' claim must be an object".into(),
            ));
        }

        let mut immediate_actor: Option<String> = None;
        let mut current = Some(act);
        let mut depth = 0;
        while let Some(entry) = current {
            if depth >= ACT_CHAIN_MAX_DEPTH {
                return Err(AuthError::InvalidToken(format!(
                    "act chain too deep (>{} hops)",
                    ACT_CHAIN_MAX_DEPTH
                )));
            }
            let actor_id = actor_identifier(entry).ok_or_else(|| {
                AuthError::InvalidToken("'act' entry missing actor identifier".into())
            })?;
            if immediate_actor.is_none() {
                immediate_actor = Some(actor_id.clone());
            }
            if let Some(may_act) = &self.config.may_act {
                if !may_act.is_authorized(&actor_id, &self.config.audiences[0]) {
                    return Err(AuthError::ActorNotAuthorized(format!(
                        "actor {:?} not authorized to act for {:?}",
                        actor_id, self.config.audiences[0]
                    )));
                }
            }
            current = entry.get("act").filter(|v| v.is_object());
            depth += 1;
        }
        Ok(immediate_actor)
    }
}

/// Decode a JWT's payload without verifying the signature. Returns the
/// raw claim object as a `serde_json::Value` map.
///
/// Used solely to read the unverified `iss` so we can look up the
/// right key. Consumers MUST follow up with a real verify().
fn unverified_claims(token: &str) -> Result<Value, AuthError> {
    use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
    let mut parts = token.split('.');
    parts.next(); // header
    let payload_b64 = parts
        .next()
        .ok_or_else(|| AuthError::InvalidToken("malformed token".into()))?;
    let bytes = URL_SAFE_NO_PAD
        .decode(payload_b64)
        .map_err(|e| AuthError::InvalidToken(format!("malformed token payload: {e}")))?;
    serde_json::from_slice(&bytes)
        .map_err(|e| AuthError::InvalidToken(format!("malformed token JSON: {e}")))
}

/// Pick the first defined of (`client_id`, `azp`, `sub`) — prefer
/// machine identity over an impersonated user.
fn actor_identifier(entry: &Value) -> Option<String> {
    for key in ["client_id", "azp", "sub"] {
        if let Some(value) = entry.get(key).and_then(|v| v.as_str()) {
            if !value.is_empty() {
                return Some(value.to_string());
            }
        }
    }
    None
}

/// Extract a string-set claim. Accepts a JSON array of strings, OR a
/// single space-separated string (OAuth 2 `scope` shape). When
/// `roles_compat` is true, also accepts comma-separated strings (the
/// shape some IdPs use for the `roles` claim).
fn extract_string_set(
    claims: &Value,
    key: &str,
    roles_compat: bool,
) -> Result<HashSet<String>, AuthError> {
    let Some(raw) = claims.get(key) else {
        return Ok(HashSet::new());
    };
    if raw.is_null() {
        return Ok(HashSet::new());
    }
    if let Some(s) = raw.as_str() {
        let normalized = if roles_compat {
            s.replace(',', " ")
        } else {
            s.to_string()
        };
        return Ok(normalized
            .split_whitespace()
            .filter(|s| !s.is_empty())
            .map(String::from)
            .collect());
    }
    if let Some(arr) = raw.as_array() {
        return Ok(arr
            .iter()
            .filter_map(|v| v.as_str().map(String::from))
            .collect());
    }
    Err(AuthError::InvalidToken(format!(
        "claim {key:?} has unexpected shape"
    )))
}
