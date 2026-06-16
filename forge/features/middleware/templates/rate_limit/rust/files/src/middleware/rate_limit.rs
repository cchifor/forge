//! Per-client token-bucket rate limiter.
//!
//! Keys on the originating client: the left-most X-Forwarded-For address when
//! present (so distinct clients behind a proxy don't share one bucket), else
//! the ConnectInfo transport peer. The bucket map is bounded (idle buckets are
//! evicted) so unique-client floods can't exhaust memory.
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
/// Cap on the number of distinct client buckets kept in memory. Once the map
/// grows past this, the least-recently-seen idle buckets are evicted. Without
/// this bound a flood of unique clients (each a fresh X-Forwarded-For address)
/// would grow the map without limit — a memory-exhaustion vector.
const MAX_BUCKETS: usize = 4096;

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
        let now = Instant::now();

        // Bound the map: if we're at capacity and this is a new key, evict
        // buckets that have been full (idle) long enough to have fully
        // refilled — they carry no state worth keeping. This keeps the map
        // from growing without bound under a flood of unique clients.
        if buckets.len() >= MAX_BUCKETS && !buckets.contains_key(key) {
            let capacity = self.capacity;
            let rate = self.rate_per_sec;
            buckets.retain(|_, b| {
                let refilled = (b.tokens + now.duration_since(b.last_refill).as_secs_f64() * rate)
                    .min(capacity);
                // Keep buckets that still owe tokens (actively limited); drop
                // ones that have fully refilled and are effectively idle.
                refilled < capacity
            });
            // If every bucket is still active (the idle retain freed nothing),
            // the map is still at the cap. Hard-bound it by evicting the
            // least-recently-used bucket (smallest last_refill) before inserting,
            // mirroring the Python limiter's OrderedDict.popitem hard cap. Without
            // this, a flood of unique active clients would grow the map without
            // limit.
            if buckets.len() >= MAX_BUCKETS {
                if let Some(lru_key) = buckets
                    .iter()
                    .min_by(|a, b| a.1.last_refill.cmp(&b.1.last_refill))
                    .map(|(k, _)| k.clone())
                {
                    buckets.remove(&lru_key);
                }
            }
        }

        let bucket = buckets.entry(key.to_string()).or_insert_with(|| Bucket {
            tokens: self.capacity,
            last_refill: now,
        });
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

    // Behind a reverse proxy / load balancer the ConnectInfo peer is the
    // proxy's address, shared by every anonymous client — keying on it would
    // collapse them all into one bucket. Prefer the left-most (originating)
    // address from X-Forwarded-For when present.
    //
    // NOTE: only trust X-Forwarded-For when the app sits behind a trusted proxy
    // that sets it; if clients can reach the app directly, strip/override the
    // header at the proxy so it can't be spoofed.
    let forwarded_ip = req
        .headers()
        .get("x-forwarded-for")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.split(',').next())
        .map(str::trim)
        .filter(|ip| !ip.is_empty())
        .map(str::to_string);

    let key = forwarded_ip
        .or_else(|| {
            // Fall back to the ConnectInfo extension (set by axum::serve
            // with_connect_info) when there's no trusted forwarded header.
            req.extensions()
                .get::<ConnectInfo<SocketAddr>>()
                .map(|ConnectInfo(addr)| addr.ip().to_string())
        })
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
