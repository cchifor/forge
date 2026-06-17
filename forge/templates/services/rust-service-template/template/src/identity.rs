//! Local IdentityContext — base-template stub.
//!
//! Repository methods, services, and route handlers take
//! ``&IdentityContext`` for tenant-scoping. The base template owns
//! this type so the codepaths compile regardless of whether the
//! platform-auth middleware fragment is applied. When the fragment is
//! on, its middleware verifies a JWT via the SDK and converts the
//! resulting ``platform_auth::IdentityContext`` into this type before
//! inserting into the request extensions (see ``From`` impl shipped by
//! the fragment at ``src/middleware/identity_compat.rs``).
//!
//! When the fragment is off, handlers still take ``&IdentityContext``
//! — applications wire a constant or test fixture in. The type stays
//! structurally compatible with the SDK's so the conversion is a
//! field-by-field copy.

use uuid::Uuid;

#[derive(Clone, Debug)]
pub struct IdentityContext {
    pub tenant_id: Uuid,
    pub tenant_slug: Option<String>,
    pub subject: String,
    pub scopes: Vec<String>,
    pub roles: Vec<String>,
    pub actor: Option<String>,
}

impl IdentityContext {
    /// Build a context with no actor / no slug — convenient for tests
    /// and for the no-auth fallback path.
    #[must_use]
    pub fn new(tenant_id: Uuid, subject: impl Into<String>) -> Self {
        Self {
            tenant_id,
            tenant_slug: None,
            subject: subject.into(),
            scopes: Vec::new(),
            roles: Vec::new(),
            actor: None,
        }
    }

    /// The canonical dev/no-auth identity bound to every request when the
    /// platform-auth middleware is NOT wired (`auth.mode=none`). Mirrors the
    /// Python and Node dev passthroughs: a fixed local tenant + user so the
    /// tenant-scoped repositories have an identity to scope on. The UUID
    /// (`00000000-0000-0000-0000-000000000001`) matches the other languages.
    #[must_use]
    pub fn dev() -> Self {
        Self {
            tenant_id: Uuid::from_u128(1),
            tenant_slug: None,
            subject: "00000000-0000-0000-0000-000000000001".to_string(),
            scopes: Vec::new(),
            roles: vec!["admin".to_string(), "user".to_string()],
            actor: None,
        }
    }
}
