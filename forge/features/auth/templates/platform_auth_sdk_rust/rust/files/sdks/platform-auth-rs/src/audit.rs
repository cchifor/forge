//! Audit-callback hook fired per allow / deny decision.
//!
//! Mirrors Python `platform_auth.auth_guard._emit_audit` and Node
//! `AuthGuard._emitAudit`: lets a host service forward every
//! verification outcome to its audit pipeline (Splunk, Loki, S3 +
//! Athena, etc.) without coupling the SDK to a specific transport.
//!
//! The record shape is the cross-language contract — fields are
//! intentionally optional so the same JSON payload can be written by
//! every language SDK without runtime keys-of-undefined surprises.
//!
//! Today only the allow-path emits; the deny path matches Python +
//! Node (where `decision = "deny"` is a forward-compat extension
//! point that hasn't been wired in yet). Keeping the parity SDKs
//! aligned is more important than running ahead — once one of the
//! three SDKs starts emitting deny, the others follow in lockstep.

use std::sync::Arc;

/// Per-verification audit record. Keep it shallow + serde-ready —
/// downstream pipelines treat the shape as the public contract.
///
/// Fields after the first four are populated when known. `tenant_id`,
/// `subject`, `actor`, and `scopes` come from the verified
/// `IdentityContext`; `jti` and `iss` come from the JWT payload;
/// `reason` is reserved for the deny path (currently unused — see
/// module docs).
#[derive(Clone, Debug)]
pub struct AuthAuditRecord {
    /// Allow or deny outcome of this verification.
    pub decision: AuthDecision,
    /// First configured verifier audience (the canonical match for
    /// metrics labels).
    pub audience: String,
    /// Every accepted audience — useful when the verifier accepts a
    /// migration window of audience values.
    pub audiences: Vec<String>,
    /// Unix-epoch seconds with sub-second precision. Aligns with
    /// Python's `time.time()` and Node's `Date.now() / 1000`.
    pub ts_unix: f64,
    pub tenant_id: Option<String>,
    /// Optional human-readable tenant slug from the verified
    /// `IdentityContext.tenant_slug`. Mirrors the per-language audit
    /// record contract — Python's `_emit_audit` and Node's
    /// `_emitAudit` carry the same field.
    pub tenant_slug: Option<String>,
    pub subject: Option<String>,
    pub actor: Option<String>,
    /// Sorted vec so two records that share a scope set produce
    /// identical downstream rows. Matches Python's `sorted(...)` and
    /// Node's `[...identity.scopes].sort()`.
    pub scopes: Option<Vec<String>>,
    pub jti: Option<String>,
    pub iss: Option<String>,
    pub reason: Option<String>,
}

/// Allow / deny outcome.
///
/// Matches Python's `decision: Literal["allow", "deny"]` and Node's
/// `decision: "allow" | "deny"`. Today only `Allow` is emitted; the
/// `Deny` variant is reserved for forward-compat parity with the
/// other SDKs.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AuthDecision {
    Allow,
    Deny,
}

impl AuthDecision {
    /// Cross-language slug — same string the Python + Node records
    /// emit. Use this when serializing the record to JSON / a metrics
    /// label, never the Rust `Debug` output.
    pub fn as_str(self) -> &'static str {
        match self {
            AuthDecision::Allow => "allow",
            AuthDecision::Deny => "deny",
        }
    }
}

/// Callback fired with the audit record.
///
/// `Arc<dyn Fn(...)>` so the verifier can clone the callback into
/// the request future without `Box`'s exclusive-ownership semantics.
/// `Send + Sync` is mandatory because verify runs across tasks on
/// the multi-threaded tokio runtime.
///
/// Implementations should be cheap (microseconds) — fire-and-forget
/// to a channel / log writer is the conventional pattern. Heavy work
/// blocks the verifier on every request.
pub type AuthAuditCallback = Arc<dyn Fn(AuthAuditRecord) + Send + Sync>;
