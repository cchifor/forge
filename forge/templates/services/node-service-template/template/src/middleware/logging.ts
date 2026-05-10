import type { FastifyReply, FastifyRequest } from "fastify";
import { logger } from "../lib/logger.js";

export async function requestLogger(req: FastifyRequest, reply: FastifyReply) {
	logger.info({
		method: req.method,
		url: req.url,
		statusCode: reply.statusCode,
		correlationId: req.correlationId,
		// `req.identity` is bound by the platform-auth plugin's onRequest
		// hook on every non-skip-listed request. May be undefined for
		// `/health`, `/metrics`, `/docs`, `/openapi.json` (skip-listed).
		tenantId: req.identity?.tenantId,
		subject: req.identity?.subject,
		responseTime: reply.elapsedTime,
	});
}
