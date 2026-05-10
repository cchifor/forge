/**
 * Type re-exports for auth-aware route handlers.
 *
 * Centralizes the SDK's identity types so route definitions don't
 * have to know which package the type comes from. Matches the
 * pattern Python services use via ``app.core.auth.User`` /
 * ``app.core.auth.IdentityContext`` re-exports.
 */

export type {
  AuthError,
  IdentityContext,
} from "@forge/platform-auth-node";

import type { FastifyRequest } from "fastify";
import type { IdentityContext } from "@forge/platform-auth-node";

/**
 * A Fastify request whose `identity` field is guaranteed bound.
 *
 * Use this in handler signatures that run AFTER the
 * `platformAuthPlugin` has verified the bearer (e.g., any handler
 * NOT in the skip-list — `/health`, `/metrics`, `/docs`,
 * `/openapi.json`).
 *
 * The plugin types `req.identity` as `IdentityContext | undefined`
 * so handlers in the skip-list can compile; this type tightens
 * it for everything else:
 *
 * ```ts
 * import type { AuthenticatedRequest } from "../types/auth.js";
 *
 * app.get("/things", async (req: AuthenticatedRequest) => {
 *   return repo.list({ tenantId: req.identity.tenantId });
 * });
 * ```
 */
export type AuthenticatedRequest = FastifyRequest & {
  identity: IdentityContext;
};
