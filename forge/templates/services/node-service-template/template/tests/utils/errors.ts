/**
 * Assertions over the RFC-007 error envelope.
 *
 * Every error response from a forge-generated backend follows the
 * shape `{ "error": { "code", "message", "type", "context",
 * "correlation_id" } }`.
 */
import { expect } from "vitest";

interface ErrorEnvelopeBody {
	error: {
		code: string;
		message: string;
		type: string;
		context: Record<string, unknown>;
		correlation_id: string;
	};
}

interface AssertOptions {
	code: string;
	statusCode: number;
	messageContains?: string;
	typeName?: string;
	contextSubset?: Record<string, unknown>;
}

interface FastifyLikeResponse {
	statusCode: number;
	payload: string;
}

export function assertErrorEnvelope(
	response: FastifyLikeResponse,
	options: AssertOptions,
): ErrorEnvelopeBody["error"] {
	expect(response.statusCode).toBe(options.statusCode);
	const body = JSON.parse(response.payload) as ErrorEnvelopeBody;
	expect(body.error).toBeDefined();
	expect(body.error.code).toBe(options.code);
	expect(body.error.correlation_id).toBeDefined();
	expect(body.error.context).toBeDefined();

	if (options.messageContains) {
		expect(body.error.message).toContain(options.messageContains);
	}
	if (options.typeName) {
		expect(body.error.type).toBe(options.typeName);
	}
	if (options.contextSubset) {
		for (const [key, value] of Object.entries(options.contextSubset)) {
			expect(body.error.context[key]).toEqual(value);
		}
	}
	return body.error;
}
