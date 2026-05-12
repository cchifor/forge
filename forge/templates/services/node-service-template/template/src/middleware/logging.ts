import type { FastifyReply, FastifyRequest } from "fastify";
import { logger } from "../lib/logger.js";
import type { IdentityContext } from "../types/auth.js";

export async function requestLogger(req: FastifyRequest, reply: FastifyReply) {
	// `req.identity` is bound by the platform-auth plugin's onRequest hook
	// on every non-skip-listed request. May be undefined for `/health`,
	// `/metrics`, `/docs`, `/openapi.json` (skip-listed) or when auth is
	// disabled entirely. The double-cast is needed because the base
	// template doesn't augment FastifyRequest — only the auth SDK does,
	// and we can't import that conditionally.
	const identity = (req as unknown as { identity?: IdentityContext }).identity;
	logger.info({
		method: req.method,
		url: req.url,
		statusCode: reply.statusCode,
		correlationId: req.correlationId,
		tenantId: identity?.tenantId,
		subject: identity?.subject,
		responseTime: reply.elapsedTime,
	});
}
