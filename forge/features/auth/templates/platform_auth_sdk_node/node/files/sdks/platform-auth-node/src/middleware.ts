/**
 * Framework-agnostic onRequest middleware factory.
 *
 * Most consumers use `platformAuthPlugin` (the Fastify plugin) for the
 * happy path. This module is the lower-level escape hatch:
 *
 *   - Tests that want to exercise the verifier without spinning up
 *     a Fastify instance.
 *   - Non-Fastify HTTP frameworks (raw `node:http`, hyper-express,
 *     uWebSockets.js, etc.) that accept an onRequest-shaped hook.
 *   - Custom Fastify integrations that need to compose the verifier
 *     with their own decoration logic.
 *
 * The factory returns a function with the shape:
 *
 *   `(request, reply) => Promise<{ identity: IdentityContext } | { rejected: true }>`
 *
 * The caller decides what to do with the rejection — Fastify's
 * `reply.send(...)` handles it; a worker would log + exit; a custom
 * integration might emit telemetry first.
 *
 * Cross-references: the Python equivalent is
 * `app/middleware/auth_context.py::AuthContextMiddleware` (FastAPI's
 * BaseHTTPMiddleware-shaped interceptor); the Rust equivalent is
 * `auth_middleware` in the Phase 7 service template (axum's
 * `from_fn`-compatible).
 */

import type { AuthGuard } from "./AuthGuard.js";
import { AuthError } from "./exceptions.js";
import type { IdentityContext } from "./IdentityContext.js";
import { DEFAULT_EXCLUDED_PATHS } from "./plugin.js";

/** Anything with a URL path + a getter for an Authorization header. */
export interface MinimalRequest {
  url?: string;
  headers: { get?(name: string): string | null } | Record<string, string | string[] | undefined>;
}

/**
 * Outcome of a single `runAuthMiddleware` invocation.
 *
 * - `verified`: the identity is bound; pass it to your handler.
 * - `excluded`: the path is in the skip-list; let the handler run
 *   without identity (e.g., `/health`).
 * - `rejected`: verification failed; the caller should send the
 *   error response (the `error` field carries the typed AuthError
 *   so the caller can map to its framework's response shape).
 */
export type AuthMiddlewareResult =
  | { kind: "verified"; identity: IdentityContext }
  | { kind: "excluded" }
  | { kind: "rejected"; error: AuthError };

export interface RunAuthMiddlewareOptions {
  /** Required: pre-constructed AuthGuard instance. */
  authGuard: AuthGuard;
  /** Optional override for the skip-list. Defaults to the same set the plugin honors. */
  excludePaths?: readonly string[];
}

/**
 * Build an onRequest-shaped function that runs the verifier.
 *
 * The returned function is thread-safe (no captured mutable state
 * beyond the `Set` of excluded paths), so a single instance can
 * service every concurrent request.
 *
 * ```ts
 * const verify = createAuthMiddleware({ authGuard });
 * server.on("request", async (req, res) => {
 *   const result = await verify(req);
 *   if (result.kind === "rejected") {
 *     res.statusCode = result.error.statusCode;
 *     res.end(JSON.stringify({ reason: result.error.reason }));
 *     return;
 *   }
 *   if (result.kind === "verified") {
 *     // Attach to wherever your framework expects.
 *     (req as any).identity = result.identity;
 *   }
 *   handle(req, res);
 * });
 * ```
 */
export function createAuthMiddleware(
  options: RunAuthMiddlewareOptions,
): (request: MinimalRequest) => Promise<AuthMiddlewareResult> {
  const skipSet = new Set(options.excludePaths ?? DEFAULT_EXCLUDED_PATHS);

  return async (request: MinimalRequest): Promise<AuthMiddlewareResult> => {
    if (request.url !== undefined && skipSet.has(request.url)) {
      return { kind: "excluded" };
    }
    try {
      const identity = await options.authGuard.verifyRequest(request);
      return { kind: "verified", identity };
    } catch (err) {
      if (err instanceof AuthError) {
        return { kind: "rejected", error: err };
      }
      // Unexpected — re-throw so the caller's framework handles it
      // via its default error path. Distinguishes "auth said no" from
      // "the verifier itself crashed".
      throw err;
    }
  };
}
