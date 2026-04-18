//! Webhook registry + HMAC-SHA256 signed outbound delivery.
//!
//! In-memory registry in v1 — single-replica only. For multi-replica
//! durability, swap the `Mutex<HashMap<...>>` for a sqlx-backed repository
//! against a `webhooks` table (mirror the Python feature's migration 0005).
//!
//! Signature header format matches the Python/Node implementations so a
//! receiver service verifies the same way across forge-generated
//! publishers:
//!     HMAC_SHA256(secret, "<timestamp>.<body>")
//! sent as the hex digest in `X-Webhook-Signature`, with `X-Webhook-Timestamp`
//! and `X-Webhook-Event` for replay-attack detection and event routing.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

use hmac::{Hmac, Mac};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::Sha256;
use uuid::Uuid;

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Webhook {
    pub id: Uuid,
    pub name: String,
    pub url: String,
    pub secret: String,
    #[serde(default)]
    pub events: Vec<String>,
    pub is_active: bool,
    #[serde(default)]
    pub extra_headers: HashMap<String, String>,
    pub created_at: String,
}

#[derive(Debug, Deserialize)]
pub struct WebhookCreate {
    pub name: String,
    pub url: String,
    #[serde(default)]
    pub events: Vec<String>,
    #[serde(default)]
    pub extra_headers: HashMap<String, String>,
}

#[derive(Debug, Serialize)]
pub struct DeliveryResult {
    pub webhook_id: Uuid,
    pub status_code: Option<u16>,
    pub ok: bool,
    pub error: Option<String>,
    pub duration_ms: u64,
}

type Registry = Arc<Mutex<HashMap<Uuid, Webhook>>>;

fn registry() -> Registry {
    static REGISTRY: OnceLock<Registry> = OnceLock::new();
    REGISTRY
        .get_or_init(|| Arc::new(Mutex::new(HashMap::new())))
        .clone()
}

fn now_iso() -> String {
    // Minimal ISO-8601 — avoid pulling in chrono if the base template doesn't already.
    // Fallback to a UNIX timestamp if the system clock is earlier than epoch.
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| {
            let secs = d.as_secs();
            let millis = d.subsec_millis();
            format!("{}.{:03}Z", secs, millis)
        })
        .unwrap_or_else(|_| "0".to_string())
}

fn generate_secret() -> String {
    format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple())
}

fn sign(secret: &str, timestamp: &str, body: &[u8]) -> String {
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes()).expect("hmac key");
    mac.update(timestamp.as_bytes());
    mac.update(b".");
    mac.update(body);
    let digest = mac.finalize().into_bytes();
    hex_encode(&digest)
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

pub fn list_webhooks() -> Vec<Webhook> {
    let mut v: Vec<Webhook> = registry().lock().unwrap().values().cloned().collect();
    v.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    v
}

pub fn create_webhook(data: WebhookCreate) -> Webhook {
    let webhook = Webhook {
        id: Uuid::new_v4(),
        name: data.name,
        url: data.url,
        secret: generate_secret(),
        events: data.events,
        is_active: true,
        extra_headers: data.extra_headers,
        created_at: now_iso(),
    };
    registry().lock().unwrap().insert(webhook.id, webhook.clone());
    webhook
}

pub fn get_webhook(id: &Uuid) -> Option<Webhook> {
    registry().lock().unwrap().get(id).cloned()
}

pub fn delete_webhook(id: &Uuid) -> bool {
    registry().lock().unwrap().remove(id).is_some()
}

pub async fn deliver(webhook: &Webhook, event: &str, payload: &Value) -> DeliveryResult {
    let start = std::time::Instant::now();
    let body = serde_json::to_vec(&serde_json::json!({ "event": event, "data": payload }))
        .unwrap_or_default();
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs().to_string())
        .unwrap_or_else(|_| "0".to_string());
    let signature = sign(&webhook.secret, &timestamp, &body);

    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build();
    let client = match client {
        Ok(c) => c,
        Err(e) => {
            return DeliveryResult {
                webhook_id: webhook.id,
                status_code: None,
                ok: false,
                error: Some(format!("client build: {}", e)),
                duration_ms: start.elapsed().as_millis() as u64,
            };
        }
    };

    let mut req = client
        .post(&webhook.url)
        .header("content-type", "application/json")
        .header("x-webhook-signature", &signature)
        .header("x-webhook-timestamp", &timestamp)
        .header("x-webhook-event", event)
        .header("x-webhook-id", webhook.id.to_string())
        .body(body);
    for (k, v) in &webhook.extra_headers {
        req = req.header(k.as_str(), v);
    }

    match req.send().await {
        Ok(resp) => {
            let code = resp.status().as_u16();
            let ok = resp.status().is_success();
            DeliveryResult {
                webhook_id: webhook.id,
                status_code: Some(code),
                ok,
                error: if ok { None } else { Some(format!("http {}", code)) },
                duration_ms: start.elapsed().as_millis() as u64,
            }
        }
        Err(e) => DeliveryResult {
            webhook_id: webhook.id,
            status_code: None,
            ok: false,
            error: Some(format!("{}", e)),
            duration_ms: start.elapsed().as_millis() as u64,
        },
    }
}
