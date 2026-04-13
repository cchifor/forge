import type { FastifyReply, FastifyRequest } from "fastify";
import { logger } from "../lib/logger.js";

export async function requestLogger(req: FastifyRequest, reply: FastifyReply) {
	logger.info({
		method: req.method,
		url: req.url,
		statusCode: reply.statusCode,
		correlationId: req.correlationId,
		customerId: req.tenant?.customerId,
		userId: req.tenant?.userId,
		responseTime: reply.elapsedTime,
	});
}
