//! Per-IP token-bucket rate limiter.
//!
//! In-memory only — fine for a single-instance deployment, unsuitable for
//! a horizontally-scaled stack (each replica maintains its own buckets).
//! Swap for a Redis-backed implementation if you deploy multiple replicas.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use axum::body::Body;
use axum::extract::ConnectInfo;
use axum::http::{Request, StatusCode};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use std::net::SocketAddr;

const REQUESTS_PER_MINUTE: f64 = 120.0;
const BURST: f64 = 120.0;

#[derive(Clone)]
pub struct RateLimiter {
    buckets: Arc<Mutex<HashMap<String, Bucket>>>,
    rate_per_sec: f64,
    capacity: f64,
}

struct Bucket {
    tokens: f64,
    last_refill: Instant,
}

impl RateLimiter {
    pub fn new() -> Self {
        Self {
            buckets: Arc::new(Mutex::new(HashMap::new())),
            rate_per_sec: REQUESTS_PER_MINUTE / 60.0,
            capacity: BURST,
        }
    }

    fn check(&self, key: &str) -> bool {
        let mut buckets = self.buckets.lock().unwrap();
        let bucket = buckets.entry(key.to_string()).or_insert_with(|| Bucket {
            tokens: self.capacity,
            last_refill: Instant::now(),
        });
        let now = Instant::now();
        let elapsed = now.duration_since(bucket.last_refill).as_secs_f64();
        bucket.tokens = (bucket.tokens + elapsed * self.rate_per_sec).min(self.capacity);
        bucket.last_refill = now;
        if bucket.tokens < 1.0 {
            return false;
        }
        bucket.tokens -= 1.0;
        true
    }
}

impl Default for RateLimiter {
    fn default() -> Self {
        Self::new()
    }
}

pub async fn rate_limit_middleware(req: Request<Body>, next: Next) -> Response {
    // Skip health/metrics paths so probes aren't rate-limited.
    let path = req.uri().path();
    if path.starts_with("/health") || path.starts_with("/metrics") {
        return next.run(req).await;
    }

    // Pull the client IP from the ConnectInfo extension (set by axum::serve with_connect_info)
    // or fall back to "anonymous" if unavailable (e.g., inside a test harness).
    let key = req
        .extensions()
        .get::<ConnectInfo<SocketAddr>>()
        .map(|ConnectInfo(addr)| addr.ip().to_string())
        .unwrap_or_else(|| "anonymous".to_string());

    // Use a per-process singleton limiter so state persists across requests.
    static LIMITER: std::sync::OnceLock<RateLimiter> = std::sync::OnceLock::new();
    let limiter = LIMITER.get_or_init(RateLimiter::new);

    if !limiter.check(&key) {
        return (
            StatusCode::TOO_MANY_REQUESTS,
            [("retry-after", "60")],
            "Rate limit exceeded. Please slow down.",
        )
            .into_response();
    }
    next.run(req).await
}
