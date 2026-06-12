//! In-process LRU cache adapter — TTL-aware [`CachePort`] implementation.
//!
//! Single-replica only. Multi-replica deployments should pick the Redis
//! adapter so eviction is consistent across pods.
//!
//! Backed by `lru::LruCache` (insertion order = LRU order, O(1) reads
//! and writes). TTL expiry is checked lazily on read (cheap timestamp
//! compare); a background sweep would be overkill for this tier.

use std::num::NonZeroUsize;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use lru::LruCache;
use serde_json::Value;
use tokio::sync::Mutex;

use crate::ports::cache::{CacheError, CachePort};

const DEFAULT_MAX_ENTRIES: usize = 1024;

fn max_entries() -> NonZeroUsize {
    let raw = std::env::var("CACHE_MEMORY_MAX_ENTRIES").ok();
    let parsed = raw
        .and_then(|s| s.parse::<usize>().ok())
        .filter(|n| *n > 0)
        .unwrap_or(DEFAULT_MAX_ENTRIES);
    NonZeroUsize::new(parsed)
        .unwrap_or_else(|| NonZeroUsize::new(DEFAULT_MAX_ENTRIES).expect("default is non-zero"))
}

struct Entry {
    value: Value,
    /// `None` means no expiry.
    expires_at: Option<Instant>,
}

/// In-process LRU cache adapter. Cheap to clone — the underlying state
/// is held behind an `Arc<Mutex>` so consumers can share one adapter.
#[derive(Clone)]
pub struct MemoryCacheAdapter {
    inner: Arc<Mutex<LruCache<String, Entry>>>,
}

impl MemoryCacheAdapter {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(LruCache::new(max_entries()))),
        }
    }

    pub fn with_capacity(capacity: NonZeroUsize) -> Self {
        Self {
            inner: Arc::new(Mutex::new(LruCache::new(capacity))),
        }
    }
}

impl Default for MemoryCacheAdapter {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl CachePort for MemoryCacheAdapter {
    async fn get(&self, key: &str) -> Result<Option<Value>, CacheError> {
        let mut guard = self.inner.lock().await;
        // ``get`` on LruCache bumps recency. If the entry is expired,
        // drop it and report a miss.
        let expired = match guard.peek(key) {
            Some(entry) => entry
                .expires_at
                .map(|deadline| Instant::now() >= deadline)
                .unwrap_or(false),
            None => return Ok(None),
        };
        if expired {
            guard.pop(key);
            return Ok(None);
        }
        Ok(guard.get(key).map(|e| e.value.clone()))
    }

    async fn set(
        &self,
        key: &str,
        value: Value,
        ttl_seconds: Option<u64>,
    ) -> Result<(), CacheError> {
        let mut guard = self.inner.lock().await;
        if let Some(secs) = ttl_seconds {
            if secs == 0 {
                guard.pop(key);
                return Ok(());
            }
        }
        let expires_at = ttl_seconds.map(|secs| Instant::now() + Duration::from_secs(secs));
        guard.put(key.to_string(), Entry { value, expires_at });
        Ok(())
    }

    async fn invalidate(&self, key: &str) -> Result<(), CacheError> {
        let mut guard = self.inner.lock().await;
        guard.pop(key);
        Ok(())
    }
}
