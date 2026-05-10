//! RFC 8693 `act` chain authorization policy.
//!
//! Mirrors Python `platform_auth.may_act` and Node `may_act.ts`: when
//! a token presents an `act` claim (this token was minted via
//! on-behalf-of token-exchange), the verifier consults a `MayActPolicy`
//! to decide whether each actor in the chain is authorized to
//! impersonate for the destination audience.
//!
//! Two ship-with-the-SDK implementations:
//!  - `AllowAllMayActPolicy` (test-only)
//!  - `StaticMayActPolicy` (fixed actor → audience allowlist)
//!
//! Production deployments that want fine-grained policy implement
//! `MayActPolicy` against their own configuration store.

use std::collections::{HashMap, HashSet};

pub trait MayActPolicy: Send + Sync {
    /// True iff `actor_id` is authorized to act for `target_audience`.
    ///
    /// `actor_id` is the immediate-actor identifier (from the `act`
    /// entry's `client_id` / `azp` / `sub`, in that priority order).
    /// `target_audience` is the audience this verifier is configured for.
    fn is_authorized(&self, actor_id: &str, target_audience: &str) -> bool;
}

/// Permissive policy — allows any actor to act for any audience.
///
/// INTENDED FOR TEST FIXTURES ONLY. Using this in production
/// effectively disables RFC 8693 authorization.
pub struct AllowAllMayActPolicy;

impl MayActPolicy for AllowAllMayActPolicy {
    fn is_authorized(&self, _actor_id: &str, _target_audience: &str) -> bool {
        true
    }
}

/// Static audience → allowed-actors map.
///
/// Mirrors Python `platform_auth.may_act.StaticMayActPolicy` and
/// Node `StaticMayActPolicy`: keyed by audience (the service the
/// verifier protects), values are the actor identifiers permitted
/// to act for that audience. Deny-by-default — an empty allowlist
/// or an unknown audience returns `false`.
///
/// Audience-keyed (rather than actor-keyed) because the verifier
/// asks "for THIS audience I serve, who is allowed?" — keying
/// matches the lookup order. Configure once at boot from the
/// service registry / tenant config / env, then attach to AuthGuard.
/// Treat as immutable after construction; reload-on-config-change
/// is the consumer's responsibility (rebuild a new policy and swap
/// the Arc).
///
/// Cross-language parity: same constructor shape across Python, Node,
/// and Rust SDKs. The shared parity-fixture suite at
/// `forge/tests/contract/auth_sdk_parity/` pins this contract.
pub struct StaticMayActPolicy {
    allowed: HashMap<String, HashSet<String>>,
}

impl StaticMayActPolicy {
    /// Build from `(audience, actors)` pairs. The first element of
    /// each pair is the audience this policy protects; the second
    /// is the iterable of actor identifiers allowed to act for it.
    pub fn new<K, V, I, J>(entries: I) -> Self
    where
        K: Into<String>,
        V: Into<String>,
        J: IntoIterator<Item = V>,
        I: IntoIterator<Item = (K, J)>,
    {
        let mut allowed: HashMap<String, HashSet<String>> = HashMap::new();
        for (audience, actors) in entries {
            let set: HashSet<String> = actors.into_iter().map(|a| a.into()).collect();
            allowed.insert(audience.into(), set);
        }
        Self { allowed }
    }
}

impl MayActPolicy for StaticMayActPolicy {
    fn is_authorized(&self, actor_id: &str, target_audience: &str) -> bool {
        if actor_id.is_empty() || target_audience.is_empty() {
            return false;
        }
        let Some(actors) = self.allowed.get(target_audience) else {
            return false;
        };
        actors.contains(actor_id)
    }
}
