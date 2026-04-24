import type { FastifyReply, FastifyRequest, preHandlerHookHandler } from "fastify";
import { AuthRequiredError } from "../lib/errors.js";

export interface TenantContext {
	userId: string;
	email: string;
	customerId: string;
	roles: string[];
}

declare module "fastify" {
	interface FastifyRequest {
		tenant: TenantContext | null;
	}
}

/**
 * Request type where `tenant` is guaranteed non-null.
 *
 * Handlers mounted inside a plugin scope that applies `requireTenant` as a
 * preHandler can accept this type directly, eliminating non-null assertions
 * (`req.tenant!`) and surfacing missing-auth bugs at TypeScript compile time
 * rather than runtime.
 */
export type AuthenticatedRequest<Req extends FastifyRequest = FastifyRequest> =
	Req & { tenant: TenantContext };

/**
 * Extract tenant context from Gatekeeper ForwardAuth headers. Registered as
 * a global `onRequest` hook so every request has `req.tenant` populated (or
 * `null`). Does NOT reject unauthenticated requests — use `requireTenant` for
 * that, mounted on a protected plugin scope.
 *
 * Gatekeeper injects these headers after validating the session cookie or API
 * key: X-Gatekeeper-User-Id, X-Gatekeeper-Email, X-Gatekeeper-Tenant,
 * X-Gatekeeper-Roles. For service-to-service calls, the caller propagates
 * these headers directly (plus `X-Customer-Id` for tenant override).
 */
export async function tenantHook(req: FastifyRequest, _reply: FastifyReply) {
	const userId = req.headers["x-gatekeeper-user-id"] as string | undefined;
	const email = (req.headers["x-gatekeeper-email"] as string) || "";
	const roles = ((req.headers["x-gatekeeper-roles"] as string) || "")
		.split(",")
		.filter(Boolean);

	const customerId =
		(req.headers["x-customer-id"] as string) || userId || null;

	if (userId && customerId) {
		req.tenant = { userId, email, customerId, roles };
	} else {
		req.tenant = null;
	}
}

/**
 * preHandler that enforces authenticated tenant context. Apply to a Fastify
 * plugin scope so every route registered inside inherits the guard:
 *
 *     await app.register(async (auth) => {
 *       auth.addHook("preHandler", requireTenant);
 *       await auth.register(itemRoutes, { prefix: "/api/v1/items" });
 *     });
 *
 * A route that needs `req.tenant` must live inside such a scope. Type
 * handlers with `AuthenticatedRequest` to make the non-null guarantee
 * statically checked.
 */
export const requireTenant: preHandlerHookHandler = async (req, _reply) => {
	if (!req.tenant) {
		throw new AuthRequiredError();
	}
};
