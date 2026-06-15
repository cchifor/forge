//! Token revocation store interface.
//!
//! Mirrors Python `platform_auth.revocation` and Node `revocation.ts`:
//! AuthGuard consults this after JWT signature/claim verification but
//! before issuing the IdentityContext. A token whose `jti` is present
//! in the store is rejected with `AuthError::TokenRevoked`.
//!
//! Intentionally minimal so consumers can back it with whatever they
//! have — Redis SET, a database table, an in-memory bloom filter for a
//! fixed denylist, etc.

use std::{
    collections::HashSet,
    sync::{Arc, Mutex},
};

use async_trait::async_trait;

#[async_trait]
pub trait RevocationStore: Send + Sync {
    /// True iff `jti` is on the revocation denylist.
    async fn is_revoked(&self, jti: &str) -> bool;
}

/// Permissive store — never reports anything as revoked.
///
/// Useful as a default when revocation isn't wired yet; AuthGuard
/// treats this as equivalent to having no store at all.
pub struct NeverRevokedStore;

#[async_trait]
impl RevocationStore for NeverRevokedStore {
    async fn is_revoked(&self, _jti: &str) -> bool {
        false
    }
}

/// In-memory denylist. Construct with the initial set; mutate via
/// `revoke()` / `unrevoke()`. NOT shared across processes — use a
/// Redis or DB-backed implementation for multi-replica deployments.
pub struct InMemoryRevocationStore {
    revoked: Arc<Mutex<HashSet<String>>>,
}

impl InMemoryRevocationStore {
    pub fn new() -> Self {
        Self {
            revoked: Arc::new(Mutex::new(HashSet::new())),
        }
    }

    pub fn with_initial<I: IntoIterator<Item = String>>(initial: I) -> Self {
        Self {
            revoked: Arc::new(Mutex::new(initial.into_iter().collect())),
        }
    }

    pub fn revoke(&self, jti: impl Into<String>) {
        self.revoked.lock().unwrap().insert(jti.into());
    }

    pub fn unrevoke(&self, jti: &str) {
        self.revoked.lock().unwrap().remove(jti);
    }
}

impl Default for InMemoryRevocationStore {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl RevocationStore for InMemoryRevocationStore {
    async fn is_revoked(&self, jti: &str) -> bool {
        self.revoked.lock().unwrap().contains(jti)
    }
}
