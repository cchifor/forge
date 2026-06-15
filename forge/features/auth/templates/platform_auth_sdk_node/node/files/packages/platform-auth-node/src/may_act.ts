/**
 * RFC 8693 ``act`` chain authorization policy.
 *
 * Mirrors Python platform_auth.may_act: when a token presents an
 * ``act`` claim (this token was minted via on-behalf-of token-exchange),
 * the verifier consults a MayActPolicy to decide whether each actor
 * in the chain is authorized to impersonate for the destination
 * audience.
 *
 * Two ship-with-the-SDK implementations:
 *  - ``AllowAllMayActPolicy``: no restriction (test-only)
 *  - ``StaticMayActPolicy``: fixed actor → audience allowlist
 *
 * Production deployments that want fine-grained policy should
 * implement ``MayActPolicy`` against their own configuration store.
 */

export interface MayActPolicy {
  /**
   * True iff ``actorId`` is authorized to act for ``targetAudience``.
   *
   * ``actorId`` is the immediate-actor identifier (from the ``act``
   * entry's ``client_id`` / ``azp`` / ``sub``, in that priority order).
   * ``targetAudience`` is the audience this verifier is configured for.
   */
  isAuthorized(actorId: string, targetAudience: string): boolean;
}

/**
 * Permissive policy — allows any actor to act for any audience.
 *
 * INTENDED FOR TEST FIXTURES ONLY. Using this in production effectively
 * disables RFC 8693 authorization.
 */
export class AllowAllMayActPolicy implements MayActPolicy {
  isAuthorized(_actorId: string, _targetAudience: string): boolean {
    return true;
  }
}

/**
 * Static audience → allowed-actors map.
 *
 * Mirrors Python ``platform_auth.may_act.StaticMayActPolicy``: keyed
 * by audience (the service the verifier protects), values are the
 * actor identifiers permitted to act for that audience. Deny-by-
 * default — an empty allowlist or an unknown audience returns
 * ``false``.
 *
 * Audience-keyed (rather than actor-keyed) because the verifier asks
 * "for THIS audience I serve, who is allowed?" — keying matches the
 * lookup order. Configure once at boot from the service registry /
 * tenant config / env, then attach to AuthGuard. Treat as immutable
 * after construction.
 *
 * Cross-language parity: same constructor shape across Python, Node,
 * and Rust SDKs. The shared parity-fixture suite at
 * ``forge/tests/contract/auth_sdk_parity/`` pins this contract.
 */
export class StaticMayActPolicy implements MayActPolicy {
  private readonly allowed: ReadonlyMap<string, ReadonlySet<string>>;

  constructor(allowed: Iterable<readonly [string, Iterable<string>]> | Record<string, Iterable<string>>) {
    const entries = Symbol.iterator in Object(allowed)
      ? (allowed as Iterable<readonly [string, Iterable<string>]>)
      : Object.entries(allowed as Record<string, Iterable<string>>);
    const built = new Map<string, ReadonlySet<string>>();
    for (const [audience, actors] of entries) {
      built.set(audience, new Set(actors));
    }
    this.allowed = built;
  }

  isAuthorized(actorId: string, targetAudience: string): boolean {
    if (!actorId || !targetAudience) {
      return false;
    }
    const actors = this.allowed.get(targetAudience);
    if (actors === undefined) {
      return false;
    }
    return actors.has(actorId);
  }
}
