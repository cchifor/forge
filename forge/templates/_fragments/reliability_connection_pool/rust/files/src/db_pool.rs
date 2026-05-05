//! sqlx pool sizing helpers with sensible defaults.
//!
//! Usage from `db.rs`:
//!
//! ```text
//! let pool = db_pool::build_pool(&settings.database_url).await?;
//! ```
//!
//! Defaults:
//!   * max_connections = 20
//!   * min_connections = 2
//!   * acquire_timeout = 10s
//!   * idle_timeout    = 10m
//!
//! All tunable via env: SQLX_MAX_CONNECTIONS, SQLX_MIN_CONNECTIONS,
//! SQLX_ACQUIRE_TIMEOUT_SECS, SQLX_IDLE_TIMEOUT_SECS.

use std::time::Duration;

use sqlx::postgres::{PgPool, PgPoolOptions};

fn env_u32(name: &str, default: u32) -> u32 {
    std::env::var(name)
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(default)
}

fn env_secs(name: &str, default: u64) -> Duration {
    Duration::from_secs(
        std::env::var(name)
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(default),
    )
}

pub async fn build_pool(database_url: &str) -> Result<PgPool, sqlx::Error> {
    PgPoolOptions::new()
        .max_connections(env_u32("SQLX_MAX_CONNECTIONS", 20))
        .min_connections(env_u32("SQLX_MIN_CONNECTIONS", 2))
        .acquire_timeout(env_secs("SQLX_ACQUIRE_TIMEOUT_SECS", 10))
        .idle_timeout(Some(env_secs("SQLX_IDLE_TIMEOUT_SECS", 600)))
        .connect(database_url)
        .await
}
