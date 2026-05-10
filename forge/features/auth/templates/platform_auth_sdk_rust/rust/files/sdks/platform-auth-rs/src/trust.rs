//! Per-tenant issuer trust map.
//!
//! Mirrors Python `platform_auth.trust` and `@forge/platform-auth-node`'s
//! `trust.ts`: each tenant declares which OIDC issuer should sign its
//! tokens. Verification rejects tokens whose `iss` claim doesn't match
//! the tenant's expected issuer (defends against a compromised second
//! issuer that could otherwise mint valid tokens for any tenant).
//!
//! The trust map is also where suspended-tenant gating happens:
//! setting `suspended: true` blocks verification regardless of token
//! validity.

use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, Instant},
};

use async_trait::async_trait;
use tokio::sync::RwLock;

/// Per-tenant trust record.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TenantTrust {
    /// Issuer URL whose tokens are accepted for this tenant.
    pub expected_issuer: String,
    /// When true, all tokens for this tenant are rejected (TenantSuspended).
    pub suspended: bool,
}

/// Async lookup interface for tenant → trust mapping.
#[async_trait]
pub trait IssuerTrustMap: Send + Sync {
    async fn get(&self, tenant_id: &str) -> Option<TenantTrust>;
}

/// In-memory map for fixed configurations. Suitable for single-tenant
/// deployments and dev/test fixtures. Multi-tenant production typically
/// fronts this with a Redis or DB-backed implementation.
pub struct InMemoryIssuerTrustMap {
    tenants: HashMap<String, TenantTrust>,
}

impl InMemoryIssuerTrustMap {
    pub fn new() -> Self {
        Self {
            tenants: HashMap::new(),
        }
    }

    pub fn with_tenants<I>(tenants: I) -> Self
    where
        I: IntoIterator<Item = (String, TenantTrust)>,
    {
        Self {
            tenants: tenants.into_iter().collect(),
        }
    }

    pub fn insert(&mut self, tenant_id: String, trust: TenantTrust) {
        self.tenants.insert(tenant_id, trust);
    }
}

impl Default for InMemoryIssuerTrustMap {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl IssuerTrustMap for InMemoryIssuerTrustMap {
    async fn get(&self, tenant_id: &str) -> Option<TenantTrust> {
        self.tenants.get(tenant_id).cloned()
    }
}

/// Wraps any IssuerTrustMap with a TTL cache to amortize lookups.
///
/// Cache invalidation is TTL-only — a tenant whose trust changes
/// upstream (suspension, issuer migration) takes up to `ttl` to
/// propagate. For immediate revocation, call `invalidate(tenant_id)`
/// from the same process that mutates the upstream store.
pub struct CachingIssuerTrustMap {
    inner: Arc<dyn IssuerTrustMap>,
    ttl: Duration,
    cache: RwLock<HashMap<String, CacheEntry>>,
}

#[derive(Clone)]
struct CacheEntry {
    value: Option<TenantTrust>,
    expires_at: Instant,
}

impl CachingIssuerTrustMap {
    pub fn new(inner: Arc<dyn IssuerTrustMap>, ttl: Duration) -> Self {
        assert!(!ttl.is_zero(), "ttl must be positive");
        Self {
            inner,
            ttl,
            cache: RwLock::new(HashMap::new()),
        }
    }

    pub async fn invalidate(&self, tenant_id: &str) {
        self.cache.write().await.remove(tenant_id);
    }
}

#[async_trait]
impl IssuerTrustMap for CachingIssuerTrustMap {
    async fn get(&self, tenant_id: &str) -> Option<TenantTrust> {
        // Fast path: hold the read lock just long enough to check.
        {
            let cache = self.cache.read().await;
            if let Some(entry) = cache.get(tenant_id) {
                if entry.expires_at > Instant::now() {
                    return entry.value.clone();
                }
            }
        }
        // Slow path: refresh under write lock. Double-check so two
        // concurrent misses on the same tenant don't both fetch.
        let mut cache = self.cache.write().await;
        if let Some(entry) = cache.get(tenant_id) {
            if entry.expires_at > Instant::now() {
                return entry.value.clone();
            }
        }
        let fresh = self.inner.get(tenant_id).await;
        cache.insert(
            tenant_id.to_string(),
            CacheEntry {
                value: fresh.clone(),
                expires_at: Instant::now() + self.ttl,
            },
        );
        fresh
    }
}
