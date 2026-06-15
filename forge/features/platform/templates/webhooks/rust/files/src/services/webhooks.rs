//! Webhook registry + HMAC-SHA256 signed outbound delivery.
//!
//! In-memory registry in v1 — single-replica only. For multi-replica
//! durability, swap the `Mutex<HashMap<...>>` for a sqlx-backed repository
//! against a `webhooks` table (mirror the Python feature's migration 0005).
//!
//! Signature header format matches the Python/Node implementations so a
//! receiver service verifies the same way across forge-generated
//! publishers:
//!     HMAC_SHA256(secret, "<timestamp>.<nonce>.<body>")
//! sent as the hex digest in `X-Webhook-Signature`, with `X-Webhook-Timestamp`
//! and `X-Webhook-Nonce` (128-bit UUID hex) for replay-attack detection,
//! and `X-Webhook-Event` for event routing. Receivers must reject stale
//! timestamps (> ~5 min) and previously-seen nonces.

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

/// Reject webhook targets that point at internal/non-public hosts (SSRF) or use
/// a non-http(s) scheme. Mirrors the Python feature's `validate_outbound_url`.
///
/// Host/scheme are parsed manually (no `url` crate) so the webhooks feature
/// pulls in no new dependency. Loopback / link-local (incl. the
/// 169.254.169.254 cloud-metadata endpoint) / RFC1918 private ranges are
/// blocked as literals; DNS names are not resolved here, so this pre-flight is
/// paired with `redirect::Policy::none()` on the client so a 3xx to an internal
/// host cannot bypass it.
fn validate_outbound_url(raw_url: &str) -> Result<(), String> {
    let (scheme, rest) = raw_url
        .split_once("://")
        .ok_or_else(|| format!("invalid webhook URL: {}", raw_url))?;
    let scheme = scheme.to_ascii_lowercase();
    if scheme != "https" && scheme != "http" {
        return Err(format!("unsupported URL scheme {}; use https", scheme));
    }
    // Authority = everything up to the first '/', '?' or '#'.
    let authority = rest
        .split(['/', '?', '#'])
        .next()
        .unwrap_or("");
    // Strip any userinfo ("user:pass@host").
    let hostport = authority.rsplit('@').next().unwrap_or(authority);
    // Pull the host out of host[:port], handling bracketed IPv6 literals.
    let host = if let Some(after) = hostport.strip_prefix('[') {
        after.split(']').next().unwrap_or("")
    } else {
        hostport.rsplit_once(':').map(|(h, _)| h).unwrap_or(hostport)
    };
    let host = host.trim().to_ascii_lowercase();
    if host.is_empty() {
        return Err("webhook URL has no host".to_string());
    }
    if is_blocked_host(&host) {
        return Err(format!("{} is a non-public address; refused", host));
    }
    Ok(())
}

fn is_blocked_host(host: &str) -> bool {
    if host == "localhost" || host.ends_with(".localhost") {
        return true;
    }
    if host.contains(':') {
        // IPv6 literal.
        if host == "::1" || host == "::" {
            return true;
        }
        // link-local fe80::/10 and unique-local fc00::/7.
        if host.starts_with("fe8")
            || host.starts_with("fe9")
            || host.starts_with("fea")
            || host.starts_with("feb")
            || host.starts_with("fc")
            || host.starts_with("fd")
        {
            return true;
        }
        // IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1).
        if let Some(mapped) = host.rsplit(':').next() {
            if mapped.contains('.') {
                return is_blocked_ipv4(mapped);
            }
        }
        return false;
    }
    is_blocked_ipv4(&host)
}

fn is_blocked_ipv4(host: &str) -> bool {
    let octets: Vec<u8> = host
        .split('.')
        .filter_map(|p| p.parse::<u8>().ok())
        .collect();
    if octets.len() != 4 || host.split('.').count() != 4 {
        return false;
    }
    let (a, b) = (octets[0], octets[1]);
    a == 127            // loopback 127.0.0.0/8
        || a == 10      // RFC1918 10.0.0.0/8
        || (a == 192 && b == 168) // RFC1918 192.168.0.0/16
        || (a == 172 && (16..=31).contains(&b)) // RFC1918 172.16.0.0/12
        || (a == 169 && b == 254) // link-local 169.254.0.0/16 (metadata)
        || a == 0       // 0.0.0.0/8 unspecified
}

fn sign(secret: &str, timestamp: &str, nonce: &str, body: &[u8]) -> String {
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes()).expect("hmac key");
    mac.update(timestamp.as_bytes());
    mac.update(b".");
    mac.update(nonce.as_bytes());
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
    registry()
        .lock()
        .unwrap()
        .insert(webhook.id, webhook.clone());
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

    // Fast pre-flight SSRF reject (scheme + host literal). Paired with the
    // no-redirect client policy below so a 3xx to an internal host can't bypass it.
    if let Err(e) = validate_outbound_url(&webhook.url) {
        return DeliveryResult {
            webhook_id: webhook.id,
            status_code: None,
            ok: false,
            error: Some(format!("refused: {}", e)),
            duration_ms: start.elapsed().as_millis() as u64,
        };
    }

    let body = serde_json::to_vec(&serde_json::json!({ "event": event, "data": payload }))
        .unwrap_or_default();
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs().to_string())
        .unwrap_or_else(|_| "0".to_string());
    let nonce = Uuid::new_v4().simple().to_string();
    let signature = sign(&webhook.secret, &timestamp, &nonce, &body);

    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        // Do not auto-follow 3xx (reqwest follows up to 10 by default): a
        // redirect to an internal host would bypass validate_outbound_url above.
        .redirect(reqwest::redirect::Policy::none())
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
        .header("x-webhook-nonce", &nonce)
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
                error: if ok {
                    None
                } else {
                    Some(format!("http {}", code))
                },
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
