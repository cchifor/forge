//! `platform-auth` — Rust SDK
//!
//! Identity, RBAC, and S2S authentication primitives for Axum services.
//! Rust port of platform-auth (Python). The public surface is
//! intentionally small — anything not in `pub use` below is an
//! implementation detail and may change without warning.
//!
//! Cross-language parity with the Python and Node SDKs is enforced by
//! the cross-SDK parity test suite at
//! `forge/tests/contract/auth_sdk_parity/` — same JWT inputs must
//! yield matching `IdentityContext` outputs (or matching `AuthError`
//! variants) across all three.
//!
//! ## Quick start
//!
//! ```no_run
//! use std::sync::Arc;
//! use platform_auth::{AuthGuard, AuthGuardConfig, JwksCache, InMemoryIssuerTrustMap, TenantTrust};
//!
//! # async fn _example() -> Result<(), platform_auth::AuthError> {
//! let jwks = Arc::new(JwksCache::default()?);
//! jwks.register_issuer(
//!     "http://gatekeeper:5000",
//!     "http://gatekeeper:5000/auth/jwks",
//! ).await?;
//!
//! let mut config = AuthGuardConfig::new("svc-things", jwks);
//! config.trust_map = Some(Arc::new(InMemoryIssuerTrustMap::with_tenants([
//!     ("00000000-0000-0000-0000-000000000001".to_string(), TenantTrust {
//!         expected_issuer: "http://gatekeeper:5000".into(),
//!         suspended: false,
//!     }),
//! ])));
//!
//! let auth = AuthGuard::new(config)?;
//! let identity = auth.verify("eyJhbGciOiJFUzI1NiIsImtpZCI6...").await?;
//! if !identity.has_scope("things:read") {
//!     // 403 Forbidden
//! }
//! # Ok(())
//! # }
//! ```

mod audit;
mod auth_guard;
mod errors;
#[cfg(feature = "axum")]
mod extractor;
mod identity;
mod jwks;
#[cfg(feature = "axum")]
mod layer;
mod may_act;
#[cfg(feature = "axum")]
mod require_scope;
mod revocation;
mod s2s_client;
mod scopes;
#[cfg(feature = "testing")]
pub mod testing;
mod trust;

pub use audit::{AuthAuditCallback, AuthAuditRecord, AuthDecision};
pub use auth_guard::{
    default_algorithms, AuthGuard, AuthGuardConfig, ACT_CHAIN_MAX_DEPTH,
    DEFAULT_CLOCK_SKEW_SECONDS, DEFAULT_ROLES_CLAIM, DEFAULT_SCOPE_CLAIM,
    DEFAULT_TENANT_ID_CLAIM, DEFAULT_TENANT_SLUG_CLAIM, REQUIRED_CLAIMS,
};
pub use errors::AuthError;
#[cfg(feature = "axum")]
pub use extractor::{IdentityRejection, OptionalIdentity};
#[cfg(feature = "axum")]
pub use layer::{AuthLayer, AuthService, DEFAULT_EXCLUDED_PATHS};
#[cfg(feature = "axum")]
pub use require_scope::{RequireScope, RequireScopeService};
pub use identity::{IdentityContext, PLATFORM_SUPPORT_READ, PLATFORM_SUPPORT_WRITE};
pub use jwks::{
    JwksCache, JwksCacheOptions, DEFAULT_HTTP_TIMEOUT_SECONDS as DEFAULT_JWKS_HTTP_TIMEOUT_SECONDS,
    DEFAULT_LIFESPAN_SECONDS, DEFAULT_STALE_MAX_SECONDS,
};
pub use may_act::{AllowAllMayActPolicy, MayActPolicy, StaticMayActPolicy};
pub use revocation::{InMemoryRevocationStore, NeverRevokedStore, RevocationStore};
pub use s2s_client::{
    CacheStats, S2SClient, S2SClientConfig, S2SRequestOptions,
    DEFAULT_HTTP_TIMEOUT_SECONDS as DEFAULT_S2S_HTTP_TIMEOUT_SECONDS,
    DEFAULT_MAX_CACHE_ENTRIES, DEFAULT_SAFETY_MARGIN_SECONDS,
};
pub use scopes::{scope_satisfies, ROOT_WILDCARD};
pub use trust::{CachingIssuerTrustMap, InMemoryIssuerTrustMap, IssuerTrustMap, TenantTrust};
