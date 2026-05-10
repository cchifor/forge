/**
 * Scope matching with wildcard support.
 *
 * Mirrors Python platform_auth.scopes: format is
 * ``<service>:<action>[:<resource>]`` with two wildcard layers — a
 * full ``*`` (god-mode) and a per-segment trailing ``*`` (e.g.,
 * ``knowledge:*`` satisfies ``knowledge:read`` and
 * ``knowledge:write``).
 *
 * Wildcards do NOT bind across segments — ``knowledge:*`` does not
 * satisfy ``knowledge:read:doc-1`` (a deeper required scope), so
 * service designers can grant coarse "do anything in this service"
 * without accidentally widening to per-resource grants.
 */

export const ROOT_WILDCARD = "*";

/**
 * True if `granted` (a set of scopes the principal holds) satisfies
 * `required` (a single scope the endpoint demands).
 *
 * Match algorithm:
 * 1. If `*` is in `granted`, allow.
 * 2. If the exact required string is in `granted`, allow.
 * 3. For each ``foo:*`` (or ``foo:bar:*``) in `granted`, allow iff
 *    `required` starts with the matching prefix.
 *
 * O(|granted|) per call. Callers verifying many scopes against the
 * same principal should pre-extract `granted` once and reuse it.
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

  // Trailing-wildcard scopes only — ``foo:*`` matches ``foo:bar`` and
  // ``foo:bar:baz``; an in-the-middle ``*`` is not a wildcard, it is
  // treated as a literal.
  for (const grant of granted) {
    if (!grant.endsWith(":*")) {
      continue;
    }
    const prefix = grant.slice(0, -1); // include the trailing ":"
    if (required.startsWith(prefix)) {
      return true;
    }
  }

  return false;
}
