/**
 * Fastify plugin entrypoint for `@forge/platform-auth-node`.
 *
 * Mirrors Python's `app/middleware/auth_context.py` + `app/core/auth.py`
 * shape for Fastify: registers an `onRequest` hook that verifies the
 * bearer once per request, decorates `req.identity` with the verified
 * `IdentityContext`, exposes an `app.requireScope(...)` decorator for
 * per-route scope enforcement, and skips a configurable list of
 * health/metrics/docs paths so probes work without auth.
 *
 * Construct one `AuthGuard` at boot and hand it to this plugin via
 * options. The plugin is encapsulation-aware (`fastify-plugin` skips
 * Fastify's default scoping so the decorations land on the parent
 * application, not the local plugin scope).
 *
 * Errors raised by the verifier are mapped to RFC 7807 problem
 * responses via `error.statusCode` and `error.reason` — clients
 * dispatch on the slug, downstream observability dashboards index
 * the problem-type URI.
 */

import type { FastifyPluginAsync, FastifyReply, FastifyRequest } from "fastify";
import fastifyPlugin from "fastify-plugin";

import { AuthError, AuthGuard, requireScope, type IdentityContext } from "./index.js";

/** Default skip-list — matches the Python middleware. */
export const DEFAULT_EXCLUDED_PATHS: readonly string[] = [
  "/health",
  "/health/live",
  "/health/ready",
  "/api/v1/health/live",
  "/api/v1/health/ready",
  "/metrics",
  "/docs",
  "/openapi.json",
];

export interface PlatformAuthPluginOptions {
  /**
   * Pre-constructed AuthGuard instance. The plugin is encapsulation-
   * neutral — it doesn't construct the AuthGuard itself so the
   * caller controls the JWKSCache / TrustMap / MayActPolicy lifecycle.
   */
  authGuard: AuthGuard;

  /**
   * Paths to skip. Defaults to the same set the Python middleware
   * skips. Pass an empty array to verify every path (rare —
   * useful for tests).
   */
  excludePaths?: readonly string[];

  /**
   * Override the request decoration name. Default `identity`.
   * Some applications want a different field on the request object
   * to avoid clashing with their own naming (e.g., `auth`).
   */
  decoratorName?: string;
}

declare module "fastify" {
  interface FastifyRequest {
    identity?: IdentityContext;
  }
  interface FastifyInstance {
    requireScope: (...required: readonly string[]) => (
      request: FastifyRequest,
      reply: FastifyReply,
    ) => Promise<void>;
  }
}

/**
 * Fastify plugin that wires the platform-auth verifier into the
 * request lifecycle. Register once at boot:
 *
 * ```ts
 * import Fastify from "fastify";
 * import { AuthGuard, JWKSCache, platformAuthPlugin } from "@forge/platform-auth-node";
 *
 * const jwks = new JWKSCache();
 * jwks.registerIssuer(process.env.GATEKEEPER_ISSUER!,
 *                      `${process.env.GATEKEEPER_ISSUER}/auth/jwks`);
 * const authGuard = new AuthGuard({
 *   audience: process.env.SERVICE_AUDIENCE!,
 *   jwks,
 *   tenantIdClaim: "https://forge/tenant_id",
 * });
 *
 * const app = Fastify();
 * await app.register(platformAuthPlugin, { authGuard });
 *
 * app.get("/things", { preHandler: app.requireScope("things:read") },
 *   async (req) => repo.list({ tenantId: req.identity!.tenantId }),
 * );
 * ```
 */
const platformAuthPluginImpl: FastifyPluginAsync<PlatformAuthPluginOptions> = async (
  fastify,
  opts,
) => {
  const excludePaths = opts.excludePaths ?? DEFAULT_EXCLUDED_PATHS;
  const skipSet = new Set(excludePaths);

  // Initialize the decoration to undefined so route handlers can
  // safely check `req.identity` without first asking if the field
  // exists. Fastify requires every decorated property to have an
  // initial value at register time.
  fastify.decorateRequest("identity", undefined);

  fastify.addHook("onRequest", async (request, reply) => {
    // Health/metrics/docs probes skip verification so they work
    // without auth — they're not request-state-bound anyway.
    if (skipSet.has(request.url) || skipSet.has(request.routeOptions?.url ?? "")) {
      return;
    }

    try {
      const identity = await opts.authGuard.verifyRequest(request);
      request.identity = identity;
    } catch (err) {
      if (err instanceof AuthError) {
        reply
          .code(err.statusCode)
          .header("WWW-Authenticate", "Bearer")
          .send({
            type: `https://forge.dev/errors/${err.reason}`,
            title: err.reason,
            status: err.statusCode,
            detail: err.message,
          });
        return;
      }
      // Unexpected — let Fastify's default error handler take it.
      throw err;
    }
  });

  // Decorate the app with `requireScope(...)` so route definitions
  // can reference it directly:
  //
  //   app.get("/things", { preHandler: app.requireScope("things:read") }, ...)
  //
  // The pre-handler runs after onRequest, so `req.identity` is
  // already bound by the time the scope check happens.
  fastify.decorate("requireScope", (...required: readonly string[]) => {
    const inner = requireScope(...required);
    return async (request: FastifyRequest, reply: FastifyReply): Promise<void> => {
      try {
        await inner(request);
      } catch (err) {
        if (err instanceof AuthError) {
          reply
            .code(err.statusCode)
            .send({
              type: `https://forge.dev/errors/${err.reason}`,
              title: err.reason,
              status: err.statusCode,
              detail: err.message,
              ...(err.extra ? { extra: err.extra } : {}),
            });
          return;
        }
        throw err;
      }
    };
  });
};

/**
 * Wrapped via `fastify-plugin` so the request decoration + the
 * `app.requireScope` decorator land on the parent application,
 * not just inside this plugin's scope. Without the wrapping,
 * Fastify would create a child scope and the decorations would
 * be invisible to consumers' route definitions.
 */
export const platformAuthPlugin = fastifyPlugin(platformAuthPluginImpl, {
  fastify: "5.x",
  name: "@forge/platform-auth-node",
});
