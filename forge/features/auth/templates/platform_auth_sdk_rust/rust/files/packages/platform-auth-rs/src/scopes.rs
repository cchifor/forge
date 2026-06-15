//! Scope matching with wildcard support.
//!
//! Mirrors Python `platform_auth.scopes` and `@forge/platform-auth-node`'s
//! `scopes.ts`: format is `<service>:<action>[:<resource>]` with two
//! wildcard layers — a full `*` (god-mode) and a per-segment trailing
//! `*` (e.g., `knowledge:*` satisfies `knowledge:read` and
//! `knowledge:write` but NOT `knowledge:read:doc-1`).
//!
//! Cross-language parity is enforced by the shared fixture suite at
//! `forge/tests/contract/auth_sdk_parity/`.

use std::collections::HashSet;

pub const ROOT_WILDCARD: &str = "*";

/// True iff `granted` (a set of scopes the principal holds) satisfies
/// `required` (a single scope the endpoint demands).
///
/// Match algorithm:
/// 1. If `*` is in `granted`, allow.
/// 2. If the exact required string is in `granted`, allow.
/// 3. For each `foo:*` (or `foo:bar:*`) in `granted`, allow iff
///    `required` starts with the matching prefix.
///
/// O(|granted|) per call. Verifying many scopes against the same
/// principal? Pre-extract `granted` once and reuse it.
pub fn scope_satisfies(required: &str, granted: &HashSet<String>) -> bool {
    if required.is_empty() {
        return true;
    }
    if granted.contains(ROOT_WILDCARD) {
        return true;
    }
    if granted.contains(required) {
        return true;
    }
    for grant in granted {
        if !grant.ends_with(":*") {
            continue;
        }
        // Include the trailing ":" — `foo:*` becomes `foo:` so we only
        // match scopes that share that exact namespace.
        let prefix = &grant[..grant.len() - 1];
        if required.starts_with(prefix) {
            return true;
        }
    }
    false
}
