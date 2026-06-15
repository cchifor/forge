//! IdentityContext — verified identity of the caller.
//!
//! Mirrors Python `platform_auth.identity.IdentityContext` and Node
//! `IdentityContext.ts`. Built by `AuthGuard::verify()` after a token
//! survives signature, issuer, audience, expiry, revocation, and
//! `may_act` checks. Service handlers consume it; nothing else in the
//! request should touch raw JWT claims.
//!
//! `Clone` so it can be passed across async boundaries without lifetime
//! gymnastics. `raw_claims` is provided for advanced uses but typed
//! accessors should be preferred.

use std::collections::HashSet;

use serde_json::Value;
use uuid::Uuid;

use crate::scopes::scope_satisfies;

/// Cross-tenant operator scopes — gating `is_platform_admin`.
pub const PLATFORM_SUPPORT_READ: &str = "platform:support:read";
pub const PLATFORM_SUPPORT_WRITE: &str = "platform:support:write";

/// Verified caller identity, immutable after construction.
#[derive(Clone, Debug)]
pub struct IdentityContext {
    pub tenant_id: Uuid,
    pub subject: String,
    pub roles: HashSet<String>,
    pub scopes: HashSet<String>,
    /// RFC 8693 immediate-actor identifier when token was minted via
    /// token-exchange; `None` for first-party (non-impersonated) tokens.
    pub actor: Option<String>,
    /// Optional human-readable tenant slug from the configured
    /// `tenant_slug_claim`. `None` when the JWT doesn't carry the
    /// claim (typical for first-party Gatekeeper-minted tokens that
    /// don't surface a slug). Consumers that need a stable identifier
    /// should always prefer `tenant_id` (UUID); the slug is for log
    /// labels and human-facing error messages.
    pub tenant_slug: Option<String>,
    /// Raw decoded JWT claims. Consume only via typed accessors.
    pub raw_claims: Value,
}

impl IdentityContext {
    /// True iff this identity's scopes satisfy `required` (wildcard-aware).
    pub fn has_scope(&self, required: &str) -> bool {
        scope_satisfies(required, &self.scopes)
    }

    /// True iff any of `required` is satisfied.
    pub fn has_any_scope<I, S>(&self, required: I) -> bool
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        required.into_iter().any(|s| self.has_scope(s.as_ref()))
    }

    /// True iff every scope in `required` is satisfied.
    pub fn has_all_scopes<I, S>(&self, required: I) -> bool
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        required.into_iter().all(|s| self.has_scope(s.as_ref()))
    }

    /// True iff this identity holds any cross-tenant `platform:support` scope.
    pub fn is_platform_admin(&self) -> bool {
        self.has_any_scope([PLATFORM_SUPPORT_READ, PLATFORM_SUPPORT_WRITE])
    }

    /// True iff this token was minted via on-behalf-of token-exchange.
    pub fn is_actor(&self) -> bool {
        self.actor.is_some()
    }
}
