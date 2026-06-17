/**
 * Dev-mode identity fallback — Node service template.
 *
 * Shipped in the base template and wired by `src/app.ts` ONLY when auth is
 * disabled (`auth.mode=none`). It binds a fixed local identity to every
 * request so the tenant-scoped repositories have a non-null `customer_id` /
 * `user_id` to scope on — exactly like the Python dev passthrough in
 * `forge_core.security.auth` (which synthesises a fixed dev user when auth is
 * disabled). Without it, `req.identity` is `undefined` and every CRUD endpoint
 * 500s in `scopeWhere`.
 *
 * When the real platform-auth plugin is wired (`auth.mode=generate`) this hook
 * is NOT registered: the plugin owns identity and rejects unauthenticated
 * requests. The default UUID matches the Python and Rust dev users for
 * cross-language parity.
 */
import type { FastifyInstance, FastifyRequest } from "fastify";
import type { IdentityContext } from "../types/auth.js";

const DEV_ID = "00000000-0000-0000-0000-000000000001";

/** The fixed identity bound to every request when auth is disabled. */
export const DEV_IDENTITY: IdentityContext = {
	tenantId: DEV_ID,
	subject: DEV_ID,
	scopes: [],
	roles: ["admin", "user"],
};

/**
 * Register an `onRequest` hook that binds {@link DEV_IDENTITY} to every
 * request. Call ONLY when auth is disabled.
 */
export function registerDevIdentity(app: FastifyInstance): void {
	app.addHook("onRequest", async (req: FastifyRequest) => {
		(req as unknown as { identity: IdentityContext }).identity = DEV_IDENTITY;
	});
}
