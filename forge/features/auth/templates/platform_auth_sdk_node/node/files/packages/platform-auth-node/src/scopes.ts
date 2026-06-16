/**
 * Scope matching with wildcard support.
 *
 * Mirrors Python platform_auth.scopes exactly: format is
 * ``<service>:<verb>[:<resource>]`` with two wildcard layers beyond the
 * full ``*`` (god-mode):
 *
 * * Verb wildcard — a held ``<prefix>:*`` satisfies ``required`` iff
 *   ``<prefix>`` is every segment of ``required`` except the last. So
 *   ``workflow:*`` covers ``workflow:read`` but NOT
 *   ``workflow:admin:retry``; ``platform:support:*`` covers
 *   ``platform:support:read`` but NOT ``platform:foo``.
 * * Namespace wildcard — a held ``*:<tail>`` satisfies ``required`` iff
 *   ``<tail>`` is every segment except the first. ``*:read`` covers
 *   ``workflow:read``; ``*:support:read`` covers
 *   ``platform:support:read``.
 *
 * Wildcards are **segment-bounded** — they do NOT bind across segments,
 * so ``workflow:*`` does not satisfy ``workflow:admin:retry`` (a deeper
 * required scope). Service designers grant coarse "do anything in this
 * service" without accidentally widening to per-resource grants.
 */

export const ROOT_WILDCARD = "*";

/**
 * True if `granted` (a set of scopes the principal holds) satisfies
 * `required` (a single scope the endpoint demands).
 *
 * Match algorithm (identical to the Python reference):
 * 1. If `*` is in `granted`, allow.
 * 2. If the exact required string is in `granted`, allow.
 * 3. Verb wildcard — synthesize ``<prefix>:*`` (every segment of
 *    `required` but the last, plus ``:*``) and allow iff it is an exact
 *    member of `granted`.
 * 4. Namespace wildcard — synthesize ``*:<tail>`` (``*:`` plus every
 *    segment but the first) and allow iff it is an exact member of
 *    `granted`.
 *
 * O(1) membership tests per call. Callers verifying many scopes against
 * the same principal should pre-extract `granted` once and reuse it.
 */
export function scopeSatisfies(required: string, granted: ReadonlySet<string>): boolean {
  if (!required) {
    return true;
  }
  if (granted.has(ROOT_WILDCARD)) {
    return true;
  }
  if (granted.has(required)) {
    return true;
  }

  const parts = required.split(":");
  if (parts.length < 2) {
    // Single-segment scopes only match exactly or via the super-wildcard.
    return false;
  }

  // Verb wildcard: ``<all-but-last>:*`` — segment-bounded, exact match.
  const verbWildcard = parts.slice(0, -1).join(":") + ":*";
  if (granted.has(verbWildcard)) {
    return true;
  }

  // Namespace wildcard: ``*:<all-but-first>`` — segment-bounded, exact match.
  const namespaceWildcard = "*:" + parts.slice(1).join(":");
  if (granted.has(namespaceWildcard)) {
    return true;
  }

  return false;
}
