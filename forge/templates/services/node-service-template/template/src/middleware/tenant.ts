import type { FastifyReply, FastifyRequest } from "fastify";

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
 * Extract tenant context from Gatekeeper ForwardAuth headers.
 *
 * Gatekeeper injects these headers after validating the session cookie or API key:
 *   X-Gatekeeper-User-Id, X-Gatekeeper-Email, X-Gatekeeper-Tenant, X-Gatekeeper-Roles
 *
 * For service-to-service calls, the caller propagates these headers directly.
 */
export async function tenantHook(req: FastifyRequest, _reply: FastifyReply) {
	const userId = req.headers["x-gatekeeper-user-id"] as string | undefined;
	const email = (req.headers["x-gatekeeper-email"] as string) || "";
	const roles = ((req.headers["x-gatekeeper-roles"] as string) || "")
		.split(",")
		.filter(Boolean);

	// x-customer-id is used for S2S tenant propagation (service account override)
	const customerId =
		(req.headers["x-customer-id"] as string) || userId || null;

	if (userId && customerId) {
		req.tenant = { userId, email, customerId, roles };
	} else {
		req.tenant = null;
	}
}
