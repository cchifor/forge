//! Cache port — capability contract for generic key/value caching.
//!
//! Distinct from any HTTP-response caching middleware — this port is the
//! **generic K/V** surface used for idempotency-key dedupe, LLM-response
//! memoization, and denormalized read caches.
//!
//! Adapters live under `src/adapters/cache_*.rs`. The port's surface is
//! intentionally minimal: `get` / `set` (with TTL) / `invalidate`. Bulk
//! and pattern-match operations are provider-specific and stay inside
//! adapters.
//!
//! Mirror of the Python `app.ports.cache.CachePort` Protocol and the
//! Node `CachePort` interface; values are JSON-serialisable and the
//! contract is identical across the three backends.

use async_trait::async_trait;
use serde_json::Value;
use thiserror::Error;

/// Error variants surfaced by [`CachePort`] operations.
#[derive(Debug, Error)]
pub enum CacheError {
    /// Underlying transport failure (Redis disconnect, etc).
    #[error("cache transport error: {0}")]
    Transport(String),
    /// Value could not be encoded / decoded as JSON.
    #[error("cache serialization error: {0}")]
    Serialization(String),
}

/// The cache port. Concrete adapters implement this trait; the rest of
/// the app depends on `dyn CachePort` (or a generic), not the adapter
/// struct.
///
/// Adapters MUST tolerate concurrent `get` / `set` / `invalidate` calls
/// on the same key.
#[async_trait]
pub trait CachePort: Send + Sync {
    /// Return the cached value for `key`, or `None` if missing or expired.
    async fn get(&self, key: &str) -> Result<Option<Value>, CacheError>;

    /// Store `value` under `key`.
    ///
    /// `ttl_seconds == None` means "no expiry" — the entry lives until
    /// explicitly invalidated or evicted by the adapter's own pressure
    /// policy (LRU for in-memory, Redis `maxmemory-policy` for Redis).
    /// `ttl_seconds == Some(0)` is treated as an immediate invalidate.
    async fn set(
        &self,
        key: &str,
        value: Value,
        ttl_seconds: Option<u64>,
    ) -> Result<(), CacheError>;

    /// Drop `key` from the cache. Idempotent — missing key is not an error.
    async fn invalidate(&self, key: &str) -> Result<(), CacheError>;
}
