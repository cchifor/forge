import type { FastifyRequest } from "fastify";

/**
 * Service-to-service HTTP client that automatically propagates tenant context
 * and correlation headers from the incoming request.
 *
 * Usage:
 *   const client = createServiceClient("http://notification:5001");
 *   const result = await client.get("/api/v1/notifications", req);
 */
export function createServiceClient(baseUrl: string) {
	function buildHeaders(req: FastifyRequest, extra?: Record<string, string>): Record<string, string> {
		const headers: Record<string, string> = {
			"content-type": "application/json",
			...extra,
		};

		// Propagate correlation ID
		if (req.correlationId) {
			headers["x-request-id"] = req.correlationId;
		}

		// Propagate tenant context (Gatekeeper headers)
		if (req.tenant) {
			headers["x-gatekeeper-user-id"] = req.tenant.userId;
			headers["x-gatekeeper-email"] = req.tenant.email;
			headers["x-gatekeeper-roles"] = req.tenant.roles.join(",");
			headers["x-customer-id"] = req.tenant.customerId;
		}

		return headers;
	}

	return {
		async get(path: string, req: FastifyRequest): Promise<Response> {
			return fetch(`${baseUrl}${path}`, {
				method: "GET",
				headers: buildHeaders(req),
			});
		},

		async post(path: string, body: unknown, req: FastifyRequest): Promise<Response> {
			return fetch(`${baseUrl}${path}`, {
				method: "POST",
				headers: buildHeaders(req),
				body: JSON.stringify(body),
			});
		},

		async patch(path: string, body: unknown, req: FastifyRequest): Promise<Response> {
			return fetch(`${baseUrl}${path}`, {
				method: "PATCH",
				headers: buildHeaders(req),
				body: JSON.stringify(body),
			});
		},

		async delete(path: string, req: FastifyRequest): Promise<Response> {
			return fetch(`${baseUrl}${path}`, {
				method: "DELETE",
				headers: buildHeaders(req),
			});
		},
	};
}
