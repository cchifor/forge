//! Multi-issuer JWKS cache.
//!
//! Mirrors Python `platform_auth.jwks.JWKSCache` and Node `JWKSCache.ts`.
//! Holds the JWKS document for each registered issuer in memory. A
//! fetch is triggered on first use, when the cache is older than
//! `lifespan`, or when a token presents a `kid` we have never seen
//! (most likely a key rotation). On upstream failure the cache serves
//! the last-known-good document for up to `stale_max` so a transient
//! IdP outage does not flatline every service.
//!
//! Concurrent `get_signing_key` calls are safe: a per-issuer
//! `tokio::Mutex` serializes refreshes, so we never thundering-herd
//! the IdP.
//!
//! Constructed once per process (typically inside AuthGuard), never
//! per-request.

use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, Instant},
};

use jsonwebtoken::{jwk::JwkSet, DecodingKey};
use reqwest::Client;
use tokio::sync::{Mutex, RwLock};

use crate::errors::AuthError;

/// Default cache lifetimes (matches Python + Node defaults).
pub const DEFAULT_LIFESPAN_SECONDS: u64 = 600; // 10 min between voluntary refreshes
pub const DEFAULT_STALE_MAX_SECONDS: u64 = 1800; // 30 min stale-serve fallback
pub const DEFAULT_HTTP_TIMEOUT_SECONDS: u64 = 5;

#[derive(Clone)]
struct CachedJwks {
    fetched_at: Instant,
    keys_by_kid: HashMap<String, DecodingKey>,
}

struct IssuerEntry {
    jwks_uri: String,
    cache: RwLock<Option<CachedJwks>>,
    /// Per-issuer mutex serializes refreshes (double-checked locking
    /// pattern: take the lock, re-check the cache, only then refetch).
    refresh_lock: Mutex<()>,
}

#[derive(Clone)]
pub struct JwksCacheOptions {
    pub lifespan: Duration,
    pub stale_max: Duration,
    pub http_timeout: Duration,
}

impl Default for JwksCacheOptions {
    fn default() -> Self {
        Self {
            lifespan: Duration::from_secs(DEFAULT_LIFESPAN_SECONDS),
            stale_max: Duration::from_secs(DEFAULT_STALE_MAX_SECONDS),
            http_timeout: Duration::from_secs(DEFAULT_HTTP_TIMEOUT_SECONDS),
        }
    }
}

/// Multi-issuer JWKS cache.
pub struct JwksCache {
    options: JwksCacheOptions,
    http: Client,
    issuers: RwLock<HashMap<String, Arc<IssuerEntry>>>,
}

impl JwksCache {
    pub fn new(options: JwksCacheOptions) -> Result<Self, AuthError> {
        if options.lifespan.is_zero() {
            return Err(AuthError::InvalidToken("lifespan must be positive".into()));
        }
        if options.stale_max < options.lifespan {
            return Err(AuthError::InvalidToken(
                "stale_max must be >= lifespan; otherwise stale-serve would be a no-op".into(),
            ));
        }
        let http = Client::builder()
            .timeout(options.http_timeout)
            .build()
            .map_err(|e| AuthError::InvalidToken(format!("HTTP client init: {e}")))?;
        Ok(Self {
            options,
            http,
            issuers: RwLock::new(HashMap::new()),
        })
    }

    /// Construct with default lifetimes. Named ``with_defaults`` rather
    /// than ``default`` because the standard ``Default::default()`` trait
    /// returns ``Self`` (infallible); this returns ``Result<Self,
    /// AuthError>``, so a Default impl would be a footgun (the panic
    /// would only fire at runtime when the options are bad).
    pub fn with_defaults() -> Result<Self, AuthError> {
        Self::new(JwksCacheOptions::default())
    }

    /// Register an issuer's JWKS URI. Idempotent for identical pairs;
    /// replacing a URI clears any cached entry so the next lookup
    /// picks up cleanly.
    pub async fn register_issuer(
        &self,
        issuer: impl Into<String>,
        jwks_uri: impl Into<String>,
    ) -> Result<(), AuthError> {
        let issuer = issuer.into();
        let jwks_uri = jwks_uri.into();
        if issuer.is_empty() {
            return Err(AuthError::InvalidToken("issuer must be non-empty".into()));
        }
        if jwks_uri.is_empty() {
            return Err(AuthError::InvalidToken("jwks_uri must be non-empty".into()));
        }
        let mut issuers = self.issuers.write().await;
        if let Some(existing) = issuers.get(&issuer) {
            if existing.jwks_uri == jwks_uri {
                return Ok(());
            }
        }
        issuers.insert(
            issuer,
            Arc::new(IssuerEntry {
                jwks_uri,
                cache: RwLock::new(None),
                refresh_lock: Mutex::new(()),
            }),
        );
        Ok(())
    }

    /// Returns the set of issuers that may be looked up.
    pub async fn registered_issuers(&self) -> Vec<String> {
        self.issuers.read().await.keys().cloned().collect()
    }

    pub async fn is_registered(&self, issuer: &str) -> bool {
        self.issuers.read().await.contains_key(issuer)
    }

    /// Returns the `DecodingKey` for `(issuer, kid)`. Refreshes the
    /// JWKS document on miss or staleness; serves stale on upstream
    /// failure for up to `stale_max`.
    pub async fn get_signing_key(&self, issuer: &str, kid: &str) -> Result<DecodingKey, AuthError> {
        let entry = {
            let issuers = self.issuers.read().await;
            issuers
                .get(issuer)
                .ok_or_else(|| {
                    AuthError::InvalidToken(format!("issuer not registered: {issuer:?}"))
                })?
                .clone()
        };

        // Fast path: fresh cache + kid present.
        {
            let cache = entry.cache.read().await;
            if let Some(cached) = cache.as_ref() {
                if cached.fetched_at.elapsed() < self.options.lifespan {
                    if let Some(key) = cached.keys_by_kid.get(kid) {
                        return Ok(key.clone());
                    }
                }
            }
        }

        // Slow path: refresh under the per-issuer lock so concurrent
        // arrivals on the same kid-rotation event share one fetch.
        let _refresh_guard = entry.refresh_lock.lock().await;

        // Re-check inside the lock.
        {
            let cache = entry.cache.read().await;
            if let Some(cached) = cache.as_ref() {
                if cached.fetched_at.elapsed() < self.options.lifespan {
                    if let Some(key) = cached.keys_by_kid.get(kid) {
                        return Ok(key.clone());
                    }
                }
            }
        }

        // Fetch.
        let fetch_result = self.fetch(&entry.jwks_uri).await;

        match fetch_result {
            Ok(fresh) => {
                let mut cache = entry.cache.write().await;
                let key = fresh.keys_by_kid.get(kid).cloned();
                *cache = Some(fresh);
                key.ok_or_else(|| {
                    AuthError::InvalidToken(format!(
                        "unknown signing key kid {kid:?} for issuer {issuer:?} (JWKS refreshed)"
                    ))
                })
            }
            Err(fetch_err) => {
                // Stale-serve on upstream failure within the staleness
                // window. Outside it, propagate the error.
                let cache = entry.cache.read().await;
                if let Some(cached) = cache.as_ref() {
                    if cached.fetched_at.elapsed() < self.options.stale_max {
                        if let Some(key) = cached.keys_by_kid.get(kid) {
                            tracing::warn!(
                                issuer = %issuer,
                                kid = %kid,
                                age_seconds = cached.fetched_at.elapsed().as_secs(),
                                error = %fetch_err,
                                "jwks_fetch_failed_serving_stale"
                            );
                            return Ok(key.clone());
                        }
                    }
                }
                Err(AuthError::InvalidToken(format!(
                    "JWKS unavailable for issuer {issuer:?} and stale window expired: {fetch_err}"
                )))
            }
        }
    }

    async fn fetch(&self, jwks_uri: &str) -> Result<CachedJwks, AuthError> {
        let resp = self
            .http
            .get(jwks_uri)
            .send()
            .await
            .map_err(AuthError::from)?;
        let status = resp.status();
        if !status.is_success() {
            return Err(AuthError::InvalidToken(format!(
                "JWKS fetch failed: HTTP {status}"
            )));
        }
        let jwk_set: JwkSet = resp.json().await.map_err(AuthError::from)?;
        let mut keys_by_kid: HashMap<String, DecodingKey> = HashMap::new();
        for jwk in &jwk_set.keys {
            // Skip keys explicitly marked for non-signing use (Keycloak
            // ships an RSA-OAEP encryption key alongside the signing
            // key by default).
            if let Some(use_) = &jwk.common.public_key_use {
                use jsonwebtoken::jwk::PublicKeyUse;
                if !matches!(use_, PublicKeyUse::Signature) {
                    continue;
                }
            }
            let Some(kid) = &jwk.common.key_id else {
                continue;
            };
            // jsonwebtoken::DecodingKey::from_jwk parses the JWK into
            // a verification key. Skip and warn on bad entries — one
            // bad key must not fail the whole fetch.
            match DecodingKey::from_jwk(jwk) {
                Ok(key) => {
                    keys_by_kid.insert(kid.clone(), key);
                }
                Err(err) => {
                    tracing::warn!(
                        kid = %kid,
                        error = %err,
                        "jwks_key_skipped"
                    );
                }
            }
        }
        if keys_by_kid.is_empty() {
            return Err(AuthError::InvalidToken(
                "JWKS document yielded no usable signing keys".into(),
            ));
        }
        Ok(CachedJwks {
            fetched_at: Instant::now(),
            keys_by_kid,
        })
    }
}
