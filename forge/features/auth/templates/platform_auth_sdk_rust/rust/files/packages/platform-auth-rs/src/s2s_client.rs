//! S2SClient — outbound service-to-service auth.
//!
//! Mirrors Python `platform_auth.s2s_client.S2SClient` and Node
//! `S2SClient.ts`. Each instance targets a single downstream
//! audience. Obtains an audience-restricted bearer via OAuth2
//! `client_credentials` (machine identity) or RFC 8693 token-exchange
//! (on-behalf-of a user), caches it until shortly before expiry, and
//! attaches it to outbound HTTP calls via
//! `Authorization: Bearer <token>`.
//!
//! ```no_run
//! use std::sync::Arc;
//! use platform_auth::{S2SClient, S2SClientConfig, S2SRequestOptions};
//!
//! # async fn _example() -> Result<(), Box<dyn std::error::Error>> {
//! let s2s = S2SClient::new(S2SClientConfig {
//!     audience: "svc-knowledge".into(),
//!     token_endpoint: "http://gatekeeper:5000/auth/token".into(),
//!     client_id: "svc-workflow".into(),
//!     client_secret: std::env::var("WORKFLOW_GATEKEEPER_SECRET")?,
//!     ..Default::default()
//! })?;
//!
//! // client_credentials grant — machine identity.
//! let response = s2s.get("http://knowledge.svc/api/items", None).await?;
//!
//! // RFC 8693 token-exchange — preserves user identity.
//! let on_behalf_of = "eyJ...".to_string();
//! let response = s2s.get(
//!     "http://knowledge.svc/api/items",
//!     Some(S2SRequestOptions {
//!         on_behalf_of: Some(on_behalf_of),
//!         tenant_id: None,
//!         extra_headers: vec![],
//!     }),
//! ).await?;
//! # Ok(())
//! # }
//! ```

use std::{collections::HashMap, sync::Arc, time::Duration};

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use moka::future::Cache;
use reqwest::{header, Client, Method, Response};
use serde::Deserialize;
use serde_json::Value;
use tokio::{
    sync::{Mutex, OnceCell},
    time::Instant,
};

use crate::errors::AuthError;

// Token-exchange grant + token type identifiers per RFC 8693.
const GRANT_CLIENT_CREDENTIALS: &str = "client_credentials";
const GRANT_TOKEN_EXCHANGE: &str = "urn:ietf:params:oauth:grant-type:token-exchange";
const TOKEN_TYPE_ACCESS: &str = "urn:ietf:params:oauth:token-type:access_token";

/// Cache key for the client_credentials token (no subject).
const CLIENT_CREDENTIALS_KEY: &str = "__client_credentials__";

/// Refresh cached tokens this many seconds before their natural expiry.
pub const DEFAULT_SAFETY_MARGIN_SECONDS: u64 = 60;

pub const DEFAULT_HTTP_TIMEOUT_SECONDS: u64 = 10;
pub const DEFAULT_MAX_CACHE_ENTRIES: u64 = 1024;

#[derive(Clone)]
struct CachedToken {
    token: String,
    /// Monotonic instant when this token's TTL elapses (minus safety margin).
    expires_at: Instant,
}

/// Snapshot of an [`S2SClient`] instance's cache counters.
///
/// Returned by [`S2SClient::cache_stats`]. Each service's metrics
/// module decides whether/how to expose these as Prometheus counters
/// — the SDK stays free of an HTTP-server / metrics framework
/// dependency.
#[derive(Clone, Debug, Default)]
pub struct CacheStats {
    pub hits: u64,
    pub misses: u64,
}

impl CacheStats {
    pub fn hit_rate(&self) -> f64 {
        let total = self.hits + self.misses;
        if total == 0 {
            0.0
        } else {
            self.hits as f64 / total as f64
        }
    }
}

/// Configuration for an [`S2SClient`] instance.
#[derive(Clone)]
pub struct S2SClientConfig {
    /// Required: downstream audience this client targets.
    pub audience: String,
    /// Required: Gatekeeper's `/auth/token` URL.
    pub token_endpoint: String,
    /// Required: this service's registered client_id.
    pub client_id: String,
    /// Required: argon2id-hashed secret pre-shared with Gatekeeper.
    pub client_secret: String,
    /// Optional: max cached tokens before LRU eviction. Default 1024.
    pub max_cache_entries: u64,
    /// Optional: refresh tokens this many seconds before their `exp`. Default 60.
    pub safety_margin_seconds: u64,
    /// Optional: HTTP timeout per call. Default 10 s.
    pub request_timeout: Duration,
}

impl Default for S2SClientConfig {
    fn default() -> Self {
        Self {
            audience: String::new(),
            token_endpoint: String::new(),
            client_id: String::new(),
            client_secret: String::new(),
            max_cache_entries: DEFAULT_MAX_CACHE_ENTRIES,
            safety_margin_seconds: DEFAULT_SAFETY_MARGIN_SECONDS,
            request_timeout: Duration::from_secs(DEFAULT_HTTP_TIMEOUT_SECONDS),
        }
    }
}

/// Per-call options passed to [`S2SClient`] HTTP methods.
#[derive(Clone, Default)]
pub struct S2SRequestOptions {
    /// Optional: when provided, performs RFC 8693 token-exchange so
    /// the downstream sees the user's identity + this service as the
    /// actor. Pass the *raw* user bearer token (without the
    /// `Bearer ` prefix).
    pub on_behalf_of: Option<String>,
    /// Optional: tenant id for multi-tenant `client_credentials`
    /// scoping. Platform extension to RFC 6749 §4.4. Ignored on
    /// token-exchange (the subject_token's tenant wins).
    pub tenant_id: Option<String>,
    /// Optional: additional HTTP headers to forward downstream.
    pub extra_headers: Vec<(String, String)>,
}

/// Audience-restricted outbound HTTP client.
pub struct S2SClient {
    config: S2SClientConfig,
    http: Client,
    tokens: Cache<String, CachedToken>,
    inflight: Mutex<HashMap<String, Arc<OnceCell<CachedToken>>>>,
    hits: Mutex<u64>,
    misses: Mutex<u64>,
}

impl S2SClient {
    pub fn new(config: S2SClientConfig) -> Result<Self, AuthError> {
        if config.audience.is_empty() {
            return Err(AuthError::S2SAuthError("audience must be non-empty".into()));
        }
        if config.token_endpoint.is_empty() {
            return Err(AuthError::S2SAuthError(
                "token_endpoint must be non-empty".into(),
            ));
        }
        if config.client_id.is_empty() {
            return Err(AuthError::S2SAuthError(
                "client_id must be non-empty".into(),
            ));
        }
        if config.client_secret.is_empty() {
            return Err(AuthError::S2SAuthError(
                "client_secret must be non-empty".into(),
            ));
        }
        if config.max_cache_entries == 0 {
            return Err(AuthError::S2SAuthError(
                "max_cache_entries must be positive".into(),
            ));
        }

        let http = Client::builder()
            .timeout(config.request_timeout)
            .build()
            .map_err(|e| AuthError::S2SAuthError(format!("HTTP client init: {e}")))?;
        let tokens = Cache::builder()
            .max_capacity(config.max_cache_entries)
            .build();
        Ok(Self {
            config,
            http,
            tokens,
            inflight: Mutex::new(HashMap::new()),
            hits: Mutex::new(0),
            misses: Mutex::new(0),
        })
    }

    /// Primary audience this client targets.
    pub fn target_audience(&self) -> &str {
        &self.config.audience
    }

    /// Return a cached or freshly-obtained token for this client's audience.
    pub async fn get_token(
        &self,
        options: Option<&S2SRequestOptions>,
    ) -> Result<String, AuthError> {
        let on_behalf_of = options.and_then(|o| o.on_behalf_of.as_deref());
        let tenant_id = options.and_then(|o| o.tenant_id.as_deref());
        let cache_key = self.cache_key(on_behalf_of, tenant_id);

        if let Some(cached) = self.tokens.get(&cache_key).await {
            if cached.expires_at > Instant::now() {
                *self.hits.lock().await += 1;
                return Ok(cached.token);
            }
        }

        // Single-flight: if another caller is already fetching for the
        // same key, await their result instead of duplicating the request.
        // Step 1: peek under the lock to decide ride-along-vs-own-fetch.
        let existing_cell = {
            let inflight = self.inflight.lock().await;
            inflight.get(&cache_key).cloned()
        };
        if let Some(existing) = existing_cell {
            // Another caller is mid-fetch — wait for the cell to be set
            // by polling its sync `get()`. Yield to the runtime so we
            // don't busy-spin if the fetch is still in flight; bound the
            // wait at 1.5× the request timeout to surface ringbuffer
            // hangs as a clear S2SAuthError rather than a deadlock.
            let deadline =
                Instant::now() + self.config.request_timeout + self.config.request_timeout / 2;
            while Instant::now() < deadline {
                if let Some(fresh) = existing.get().cloned() {
                    *self.hits.lock().await += 1;
                    return Ok(fresh.token);
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            // Fall through and own-fetch — the other caller's request
            // didn't complete in time; better to duplicate than to hang.
        }

        // Step 2: insert our own cell and proceed to fetch.
        let cell = {
            let mut inflight = self.inflight.lock().await;
            // Re-check: another caller might have finished and inserted
            // between our peek and this lock.
            if let Some(existing) = inflight.get(&cache_key).cloned() {
                if let Some(fresh) = existing.get().cloned() {
                    drop(inflight);
                    *self.hits.lock().await += 1;
                    return Ok(fresh.token);
                }
            }
            let cell = Arc::new(OnceCell::new());
            inflight.insert(cache_key.clone(), cell.clone());
            cell
        };

        *self.misses.lock().await += 1;
        let result = self.fetch_token(on_behalf_of, tenant_id).await;

        // Always remove the inflight entry; the cache holds the success.
        self.inflight.lock().await.remove(&cache_key);

        let fresh = result?;
        let _ = cell.set(fresh.clone());
        self.tokens.insert(cache_key, fresh.clone()).await;
        Ok(fresh.token)
    }

    /// Drop the cached token for this subject. The next call refetches.
    /// Useful when the downstream returned 401 (token might be revoked
    /// upstream while still inside our cache window).
    pub async fn invalidate(&self, options: Option<&S2SRequestOptions>) {
        let on_behalf_of = options.and_then(|o| o.on_behalf_of.as_deref());
        let tenant_id = options.and_then(|o| o.tenant_id.as_deref());
        let cache_key = self.cache_key(on_behalf_of, tenant_id);
        self.tokens.invalidate(&cache_key).await;
    }

    /// Drop every cached token. Use sparingly.
    pub async fn clear_cache(&self) {
        self.tokens.invalidate_all();
        // Force eviction so a follow-up `cache_stats()` reflects
        // the empty state immediately.
        self.tokens.run_pending_tasks().await;
    }

    pub async fn cache_stats(&self) -> CacheStats {
        CacheStats {
            hits: *self.hits.lock().await,
            misses: *self.misses.lock().await,
        }
    }

    // ---------------------------------------------------------------- HTTP API

    /// Send an authenticated request. On a 401 response, drops the
    /// cached token and retries once.
    pub async fn request(
        &self,
        method: Method,
        url: &str,
        options: Option<S2SRequestOptions>,
    ) -> Result<Response, AuthError> {
        let opts_ref = options.as_ref();
        let token = self.get_token(opts_ref).await?;

        let response = self.do_send(method.clone(), url, &token, opts_ref).await?;
        if response.status() == reqwest::StatusCode::UNAUTHORIZED {
            // Stale token — refetch and try once more.
            self.invalidate(opts_ref).await;
            let fresh_token = self.get_token(opts_ref).await?;
            return self.do_send(method, url, &fresh_token, opts_ref).await;
        }
        Ok(response)
    }

    pub async fn get(
        &self,
        url: &str,
        options: Option<S2SRequestOptions>,
    ) -> Result<Response, AuthError> {
        self.request(Method::GET, url, options).await
    }

    pub async fn post(
        &self,
        url: &str,
        options: Option<S2SRequestOptions>,
    ) -> Result<Response, AuthError> {
        self.request(Method::POST, url, options).await
    }

    pub async fn put(
        &self,
        url: &str,
        options: Option<S2SRequestOptions>,
    ) -> Result<Response, AuthError> {
        self.request(Method::PUT, url, options).await
    }

    pub async fn patch(
        &self,
        url: &str,
        options: Option<S2SRequestOptions>,
    ) -> Result<Response, AuthError> {
        self.request(Method::PATCH, url, options).await
    }

    pub async fn delete(
        &self,
        url: &str,
        options: Option<S2SRequestOptions>,
    ) -> Result<Response, AuthError> {
        self.request(Method::DELETE, url, options).await
    }

    // ---------------------------------------------------------------- internals

    async fn do_send(
        &self,
        method: Method,
        url: &str,
        token: &str,
        options: Option<&S2SRequestOptions>,
    ) -> Result<Response, AuthError> {
        let mut req = self.http.request(method, url).bearer_auth(token);
        if let Some(opts) = options {
            for (key, value) in &opts.extra_headers {
                req = req.header(key, value);
            }
        }
        req.send()
            .await
            .map_err(|err| AuthError::S2SAuthError(format!("downstream call failed: {err}")))
    }

    fn cache_key(&self, on_behalf_of: Option<&str>, tenant_id: Option<&str>) -> String {
        let suffix = tenant_id
            .map(|t| format!(":tenant:{t}"))
            .unwrap_or_default();
        match on_behalf_of {
            None => format!("{CLIENT_CREDENTIALS_KEY}{suffix}"),
            Some(token) => match unverified_jti(token) {
                Some(jti) => format!("obo:jti:{jti}{suffix}"),
                None => format!("obo:hash:{}{suffix}", short_hash(token)),
            },
        }
    }

    async fn fetch_token(
        &self,
        on_behalf_of: Option<&str>,
        tenant_id: Option<&str>,
    ) -> Result<CachedToken, AuthError> {
        let mut form: Vec<(&str, String)> = vec![
            ("client_id", self.config.client_id.clone()),
            ("client_secret", self.config.client_secret.clone()),
            ("audience", self.config.audience.clone()),
        ];
        match on_behalf_of {
            None => {
                form.push(("grant_type", GRANT_CLIENT_CREDENTIALS.to_string()));
                if let Some(tid) = tenant_id {
                    form.push(("tenant_id", tid.to_string()));
                }
            }
            Some(token) => {
                form.push(("grant_type", GRANT_TOKEN_EXCHANGE.to_string()));
                form.push(("subject_token", token.to_string()));
                form.push(("subject_token_type", TOKEN_TYPE_ACCESS.to_string()));
                // tenant_id ignored on token-exchange — the subject_token's
                // tenant is the source of truth.
            }
        }

        let response = self
            .http
            .post(&self.config.token_endpoint)
            .header(header::CONTENT_TYPE, "application/x-www-form-urlencoded")
            .form(&form)
            .send()
            .await
            .map_err(|err| AuthError::S2SAuthError(format!("token endpoint unreachable: {err}")))?;

        let status = response.status();
        if !status.is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "<unreadable>".into());
            return Err(AuthError::S2SAuthError(format!(
                "token endpoint returned HTTP {status}: {}",
                body.chars().take(200).collect::<String>()
            )));
        }

        let payload: TokenResponse = response.json().await.map_err(|err| {
            AuthError::S2SAuthError(format!("token endpoint returned non-JSON response: {err}"))
        })?;
        if payload.access_token.is_empty() {
            return Err(AuthError::S2SAuthError(
                "token endpoint response missing 'access_token'".into(),
            ));
        }
        // Spec-compliant servers always return a positive `expires_in`;
        // default defensively (matching Python `expires_in <= 0` and
        // Node `rawExpiresIn > 0 ? rawExpiresIn : 300`) so a missing or
        // non-positive value yields a usable TTL instead of a token
        // that's never cached.
        let expires_in = match payload.expires_in {
            Some(n) if n > 0 => n,
            _ => 300,
        };
        let safety = self.config.safety_margin_seconds.min(expires_in);
        let ttl = Duration::from_secs(expires_in - safety);
        Ok(CachedToken {
            token: payload.access_token,
            expires_at: Instant::now() + ttl,
        })
    }
}

#[derive(Deserialize)]
struct TokenResponse {
    access_token: String,
    #[serde(default)]
    expires_in: Option<u64>,
}

/// Decode a JWT's `jti` without verifying the signature.
fn unverified_jti(token: &str) -> Option<String> {
    let mut parts = token.split('.');
    let _header = parts.next()?;
    let payload_b64 = parts.next()?;
    let bytes = URL_SAFE_NO_PAD.decode(payload_b64).ok()?;
    let claims: Value = serde_json::from_slice(&bytes).ok()?;
    claims
        .get("jti")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(String::from)
}

/// Short stable hash for cache keys when the subject token has no jti.
/// FNV-1a 64-bit, fast and stable across compilations — matches Node's
/// approach but with a different prime so cross-language cache keys
/// for the same un-jti'd token differ (this is fine: the cache is
/// per-process and per-language anyway).
fn short_hash(input: &str) -> String {
    let mut hash: u64 = 0xcbf29ce484222325;
    let prime: u64 = 0x100000001b3;
    for byte in input.bytes() {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(prime);
    }
    format!("{hash:016x}")
}
