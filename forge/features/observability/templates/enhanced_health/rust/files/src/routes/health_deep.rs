//! Deep readiness endpoint: pings Redis (TCP) + Keycloak (HTTP).
//!
//! Kept framework-minimal so it doesn't drag in the redis crate. TCP-ping
//! Redis is sufficient for a readiness gate — the primary goal is "can we
//! reach the dependency", not "is our client configured". Use the redis
//! crate directly in your own handlers once you need real Redis operations.

use std::time::{Duration, Instant};

use axum::http::StatusCode;
use axum::response::{IntoResponse, Json};
use axum::routing::get;
use axum::Router;
use serde::Serialize;
use tokio::net::TcpStream;
use tokio::time::timeout;

#[derive(Serialize)]
struct CheckResult {
    status: &'static str,
    latency_ms: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

#[derive(Serialize)]
struct DeepReadiness {
    status: &'static str,
    components: ComponentMap,
}

#[derive(Serialize)]
struct ComponentMap {
    redis: CheckResult,
    keycloak: CheckResult,
}

pub fn deep_health_router<S>() -> Router<S>
where
    S: Clone + Send + Sync + 'static,
{
    Router::new().route("/deep", get(deep_handler))
}

async fn deep_handler() -> impl IntoResponse {
    let redis = check_redis().await;
    let keycloak = check_keycloak().await;
    let up = redis.status == "up" && keycloak.status == "up";
    let body = DeepReadiness {
        status: if up { "up" } else { "down" },
        components: ComponentMap { redis, keycloak },
    };
    let code = if up {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };
    (code, Json(body))
}

async fn check_redis() -> CheckResult {
    // Accept either redis:// or rediss:// URLs; strip the scheme to get host:port.
    let url =
        std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://redis:6379".to_string());
    let target = parse_redis_target(&url);
    let start = Instant::now();
    match timeout(Duration::from_secs(2), TcpStream::connect(&target)).await {
        Ok(Ok(_)) => CheckResult {
            status: "up",
            latency_ms: start.elapsed().as_millis() as u64,
            error: None,
        },
        Ok(Err(e)) => CheckResult {
            status: "down",
            latency_ms: start.elapsed().as_millis() as u64,
            error: Some(format!("connect: {}", e)),
        },
        Err(_) => CheckResult {
            status: "down",
            latency_ms: start.elapsed().as_millis() as u64,
            error: Some("timeout".to_string()),
        },
    }
}

fn parse_redis_target(url: &str) -> String {
    let stripped = url
        .strip_prefix("redis://")
        .or_else(|| url.strip_prefix("rediss://"))
        .unwrap_or(url);
    // Drop any path suffix like "/0" (selects a DB — we only need host:port).
    let host_port = stripped.split('/').next().unwrap_or(stripped);
    // If a username/password is present (user:pass@host:port), take everything after '@'.
    host_port
        .rsplit_once('@')
        .map(|(_, hp)| hp.to_string())
        .unwrap_or_else(|| host_port.to_string())
}

async fn check_keycloak() -> CheckResult {
    let url = std::env::var("KEYCLOAK_HEALTH_URL")
        .unwrap_or_else(|_| "http://keycloak:9000/health/ready".to_string());
    let start = Instant::now();
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(3))
        .build();
    let client = match client {
        Ok(c) => c,
        Err(e) => {
            return CheckResult {
                status: "down",
                latency_ms: start.elapsed().as_millis() as u64,
                error: Some(format!("client build: {}", e)),
            };
        }
    };
    match client.get(&url).send().await {
        Ok(resp) if resp.status().is_success() => CheckResult {
            status: "up",
            latency_ms: start.elapsed().as_millis() as u64,
            error: None,
        },
        Ok(resp) => CheckResult {
            status: "down",
            latency_ms: start.elapsed().as_millis() as u64,
            error: Some(format!("http {}", resp.status())),
        },
        Err(e) => CheckResult {
            status: "down",
            latency_ms: start.elapsed().as_millis() as u64,
            error: Some(format!("{}", e)),
        },
    }
}
