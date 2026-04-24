import type { FastifyError, FastifyReply, FastifyRequest } from "fastify";
import { ZodError } from "zod";
import { AppError } from "../lib/errors.js";
import { logger } from "../lib/logger.js";

/**
 * RFC-007 error envelope. Every error response from this service is
 * serialized into this shape. See docs/rfcs/RFC-007-error-contract.md.
 */
interface ErrorEnvelope {
	error: {
		code: string;
		message: string;
		type: string;
		context: Record<string, unknown>;
		correlation_id: string;
	};
}

function correlationIdOf(req: FastifyRequest): string {
	const headers = req.headers as Record<string, string | string[] | undefined>;
	const raw = headers["x-correlation-id"];
	if (typeof raw === "string") return raw;
	if (Array.isArray(raw) && raw.length > 0) return raw[0] ?? "";
	return (req.id as string | undefined) ?? "";
}

function envelope(
	req: FastifyRequest,
	code: string,
	message: string,
	type: string,
	context: Record<string, unknown> = {},
): ErrorEnvelope {
	return {
		error: {
			code,
			message,
			type,
			context,
			correlation_id: correlationIdOf(req),
		},
	};
}

export function errorHandler(
	error: FastifyError,
	req: FastifyRequest,
	reply: FastifyReply,
) {
	if (error instanceof AppError) {
		return reply
			.code(error.statusCode)
			.send(envelope(req, error.code, error.message, error.name, error.context));
	}

	if (error instanceof ZodError) {
		const message = error.errors
			.map((e) => `${e.path.join(".")}: ${e.message}`)
			.join("; ");
		return reply.code(422).send(
			envelope(req, "VALIDATION_FAILED", message, "ValidationError", {
				errors: error.errors.map((e) => ({
					path: e.path,
					message: e.message,
					code: e.code,
				})),
			}),
		);
	}

	// Fastify surfaces body-validation / 4xx framework errors with a statusCode.
	// Preserve client-facing context but route through the canonical envelope.
	const frameworkStatus = error.statusCode ?? 0;
	if (frameworkStatus >= 400 && frameworkStatus < 500) {
		return reply.code(frameworkStatus).send(
			envelope(
				req,
				frameworkStatus === 429 ? "RATE_LIMITED" : "INVALID_INPUT",
				error.message,
				error.name || "FastifyError",
			),
		);
	}

	logger.error({ err: error, correlationId: correlationIdOf(req) }, "Unhandled error");
	return reply
		.code(500)
		.send(
			envelope(
				req,
				"INTERNAL_ERROR",
				"An unexpected error occurred",
				"InternalError",
			),
		);
}
