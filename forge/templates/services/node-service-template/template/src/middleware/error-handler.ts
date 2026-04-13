import type { FastifyError, FastifyReply, FastifyRequest } from "fastify";
import { ZodError } from "zod";
import { AppError } from "../lib/errors.js";
import { logger } from "../lib/logger.js";

export function errorHandler(error: FastifyError, _req: FastifyRequest, reply: FastifyReply) {
	if (error instanceof AppError) {
		return reply.code(error.statusCode).send({
			statusCode: error.statusCode,
			error: error.name,
			message: error.message,
		});
	}

	if (error instanceof ZodError) {
		return reply.code(422).send({
			statusCode: 422,
			error: "ValidationError",
			message: error.errors.map((e) => `${e.path.join(".")}: ${e.message}`).join("; "),
		});
	}

	logger.error(error, "Unhandled error");
	return reply.code(500).send({
		statusCode: 500,
		error: "InternalServerError",
		message: "An unexpected error occurred",
	});
}
