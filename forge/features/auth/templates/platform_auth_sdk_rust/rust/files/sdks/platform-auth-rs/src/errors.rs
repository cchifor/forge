//! Error hierarchy for `platform-auth-rs`.
//!
//! Mirrors Python `platform_auth.exceptions`: every variant carries a
//! stable `reason` slug and an HTTP-equivalent `status_code` so callers
//! can map them directly to RFC 7807 problem responses without sniffing
//! the type tree. The slugs are part of the cross-language public
//! contract — clients dispatch on them, so changing one is a breaking
//! change across Python, Node, and Rust.

use std::collections::HashSet;

use thiserror::Error;

/// Top-level auth failure.
///
/// The `From` impls below let callers `?` jose-style errors directly;
/// the verifier translates them to typed variants before they escape
/// the SDK boundary.
#[derive(Debug, Error)]
pub enum AuthError {
    #[error("invalid_token: {0}")]
    InvalidToken(String),

    #[error("token_expired: {0}")]
    TokenExpired(String),

    #[error("token_revoked: {0}")]
    TokenRevoked(String),

    #[error("issuer_not_trusted: {0}")]
    IssuerNotTrusted(String),

    #[error("actor_not_authorized: {0}")]
    ActorNotAuthorized(String),

    #[error("scope_required: {missing:?}")]
    ScopeRequired { missing: HashSet<String> },

    #[error("tenant_suspended: {0}")]
    TenantSuspended(String),

    #[error("s2s_auth_error: {0}")]
    S2SAuthError(String),
}

impl AuthError {
    /// Stable snake_case slug for client-side dispatch. Public contract.
    pub fn reason(&self) -> &'static str {
        match self {
            Self::InvalidToken(_) => "invalid_token",
            Self::TokenExpired(_) => "token_expired",
            Self::TokenRevoked(_) => "token_revoked",
            Self::IssuerNotTrusted(_) => "issuer_not_trusted",
            Self::ActorNotAuthorized(_) => "actor_not_authorized",
            Self::ScopeRequired { .. } => "scope_required",
            Self::TenantSuspended(_) => "tenant_suspended",
            Self::S2SAuthError(_) => "s2s_auth_error",
        }
    }

    /// HTTP status code for the problem-response mapping.
    ///
    /// 401 for credential failures (token bad / missing / expired /
    /// revoked / wrong issuer), 403 for authorization failures
    /// (scope missing, tenant suspended, actor not allowed), 503 for
    /// outbound S2S failures (this service depends on an upstream
    /// that is currently failing — distinct from inbound 401/403).
    pub fn status_code(&self) -> u16 {
        match self {
            Self::InvalidToken(_)
            | Self::TokenExpired(_)
            | Self::TokenRevoked(_)
            | Self::IssuerNotTrusted(_) => 401,
            Self::ActorNotAuthorized(_)
            | Self::ScopeRequired { .. }
            | Self::TenantSuspended(_) => 403,
            Self::S2SAuthError(_) => 503,
        }
    }
}

/// jsonwebtoken's typed errors map directly to InvalidToken /
/// TokenExpired with a few exceptions; the verifier inspects the kind
/// before wrapping so the caller sees the right status code.
impl From<jsonwebtoken::errors::Error> for AuthError {
    fn from(err: jsonwebtoken::errors::Error) -> Self {
        use jsonwebtoken::errors::ErrorKind;
        match err.kind() {
            ErrorKind::ExpiredSignature => Self::TokenExpired(err.to_string()),
            ErrorKind::ImmatureSignature => {
                Self::InvalidToken(format!("token not yet valid (nbf in future): {err}"))
            }
            ErrorKind::InvalidAudience => {
                Self::InvalidToken(format!("audience mismatch: {err}"))
            }
            ErrorKind::InvalidIssuer => Self::InvalidToken(format!("issuer mismatch: {err}")),
            ErrorKind::InvalidSignature => {
                Self::InvalidToken(format!("signature mismatch: {err}"))
            }
            ErrorKind::MissingRequiredClaim(claim) => {
                Self::InvalidToken(format!("missing required claim: {claim}"))
            }
            _ => Self::InvalidToken(err.to_string()),
        }
    }
}

/// HTTP-layer errors during JWKS fetch or S2S token-endpoint calls
/// surface as InvalidToken (inbound) or S2SAuthError (outbound). The
/// caller decides which conversion is appropriate via explicit
/// wrapping; this conversion is the conservative default.
impl From<reqwest::Error> for AuthError {
    fn from(err: reqwest::Error) -> Self {
        Self::InvalidToken(format!("upstream HTTP error: {err}"))
    }
}
