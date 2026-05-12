/**
 * Type re-exports for auth-aware route handlers — base-template stub.
 *
 * The base service template references these types throughout (route
 * handlers, repository methods, services) so the codepaths compile
 * regardless of whether ``auth.mode=generate`` is enabled. When the
 * platform-auth middleware fragment is applied, it overwrites this
 * file with one that re-exports from ``@forge/platform-auth-node``.
 *
 * The stub keeps the shapes minimal but compatible with the real SDK
 * surface so ``tsc --noEmit`` passes without auth wired in. At
 * runtime, ``identity`` is bound by the auth plugin (when present) or
 * forge-toml-disabled — handlers don't have to defensively check.
 */

import type { FastifyRequest } from "fastify";

export interface IdentityContext {
  tenantId: string;
  subject: string;
  scopes: readonly string[];
  roles: readonly string[];
  actor?: string;
}

export interface AuthError {
  reason: string;
  statusCode: number;
}

export type AuthenticatedRequest = FastifyRequest & {
  identity: IdentityContext;
};

// Note: the ``FastifyRequest.identity`` augmentation lives in the SDK's
// ``plugin.ts`` (when the auth fragment is enabled and the SDK ships
// the plugin alongside the consumer). Augmenting it here would
// conflict with the SDK's declaration once both are in the type graph
// — same property name, different ``IdentityContext`` definitions.
// Handlers that need to read ``req.identity`` without depending on the
// SDK being installed should cast via the type below:
//
//   const identity = (req as unknown as { identity?: IdentityContext }).identity;
//
// When the SDK is installed, the augmentation provides ``identity``
// directly on ``FastifyRequest`` and the cast is a no-op.

/**
 * Build an ``IdentityContext`` with sensible defaults — mirrors the
 * SDK's ``buildIdentity`` helper so tests and dev fixtures can import
 * from ``../types/auth.js`` regardless of whether the auth fragment
 * is enabled.
 */
export function buildIdentity(init: {
  tenantId: string;
  subject: string;
  scopes?: readonly string[];
  roles?: readonly string[];
  actor?: string;
}): IdentityContext {
  return {
    tenantId: init.tenantId,
    subject: init.subject,
    scopes: init.scopes ?? [],
    roles: init.roles ?? [],
    ...(init.actor !== undefined ? { actor: init.actor } : {}),
  };
}
