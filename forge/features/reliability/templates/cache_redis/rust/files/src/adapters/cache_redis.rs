//! Redis cache adapter — [`CachePort`] implementation backed by the
//! `redis` crate's tokio async client.
//!
//! Values are stored as JSON; non-JSON-serialisable values surface as
//! [`CacheError::Serialization`] at `set` time. Cross-replica safe —
//! eviction is governed by Redis's `maxmemory-policy` (typically
//! `allkeys-lru`).
//!
//! Shares the Redis sidecar with queue/rate-limit fragments via the
//! standard `REDIS_URL` env var; cache traffic runs on a dedicated DB
//! (default `/3`) so eviction pressure doesn't clobber queue keysets.

use async_trait::async_trait;
use redis::{AsyncCommands, Client};
use serde_json::Value;
use tokio::sync::Mutex;

use crate::ports::cache::{CacheError, CachePort};

const DEFAULT_URL: &str = "redis://redis:6379/3";

fn cache_url() -> String {
    std::env::var("CACHE_REDIS_URL").unwrap_or_else(|_| DEFAULT_URL.to_string())
}

/// Redis cache adapter. The underlying client is wrapped in an `Arc<Mutex>`
/// so callers can share one adapter across tokio tasks; for higher
/// throughput, swap in a connection pool (`bb8-redis` / `deadpool-redis`).
pub struct RedisCacheAdapter {
    client: Client,
    // A single multiplexed connection re-used per-call. The Mutex
    // serializes pipelined writes, which is fine for the scaffolding —
    // production code should wire a real pool (see module docstring).
    conn: Mutex<Option<redis::aio::MultiplexedConnection>>,
}

impl RedisCacheAdapter {
    pub fn new() -> Result<Self, CacheError> {
        let client =
            Client::open(cache_url()).map_err(|e| CacheError::Transport(e.to_string()))?;
        Ok(Self {
            client,
            conn: Mutex::new(None),
        })
    }

    pub fn with_url(url: &str) -> Result<Self, CacheError> {
        let client = Client::open(url).map_err(|e| CacheError::Transport(e.to_string()))?;
        Ok(Self {
            client,
            conn: Mutex::new(None),
        })
    }

    async fn connection(&self) -> Result<redis::aio::MultiplexedConnection, CacheError> {
        let mut guard = self.conn.lock().await;
        if let Some(c) = guard.as_ref() {
            return Ok(c.clone());
        }
        let new_conn = self
            .client
            .get_multiplexed_async_connection()
            .await
            .map_err(|e| CacheError::Transport(e.to_string()))?;
        *guard = Some(new_conn.clone());
        Ok(new_conn)
    }
}

#[async_trait]
impl CachePort for RedisCacheAdapter {
    async fn get(&self, key: &str) -> Result<Option<Value>, CacheError> {
        let mut conn = self.connection().await?;
        let raw: Option<String> = conn
            .get(key)
            .await
            .map_err(|e| CacheError::Transport(e.to_string()))?;
        match raw {
            None => Ok(None),
            Some(s) => {
                // Tolerate raw-string writes from ops tools (redis-cli)
                // by falling back to a JSON string value.
                let parsed = serde_json::from_str::<Value>(&s).unwrap_or(Value::String(s));
                Ok(Some(parsed))
            }
        }
    }

    async fn set(
        &self,
        key: &str,
        value: Value,
        ttl_seconds: Option<u64>,
    ) -> Result<(), CacheError> {
        let mut conn = self.connection().await?;
        if let Some(secs) = ttl_seconds {
            if secs == 0 {
                let _: () = conn
                    .del(key)
                    .await
                    .map_err(|e| CacheError::Transport(e.to_string()))?;
                return Ok(());
            }
        }
        let payload = serde_json::to_string(&value)
            .map_err(|e| CacheError::Serialization(e.to_string()))?;
        match ttl_seconds {
            None => {
                let _: () = conn
                    .set(key, payload)
                    .await
                    .map_err(|e| CacheError::Transport(e.to_string()))?;
            }
            Some(secs) => {
                let _: () = conn
                    .set_ex(key, payload, secs)
                    .await
                    .map_err(|e| CacheError::Transport(e.to_string()))?;
            }
        }
        Ok(())
    }

    async fn invalidate(&self, key: &str) -> Result<(), CacheError> {
        let mut conn = self.connection().await?;
        let _: () = conn
            .del(key)
            .await
            .map_err(|e| CacheError::Transport(e.to_string()))?;
        Ok(())
    }
}
