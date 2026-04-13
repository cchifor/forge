import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createServiceClient } from "../../src/lib/http-client.js";
import type { FastifyRequest } from "fastify";

// Mock global fetch
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function createMockRequest(overrides?: Partial<FastifyRequest>): FastifyRequest {
	return {
		correlationId: "req-123",
		tenant: {
			userId: "user-001",
			email: "user@example.com",
			customerId: "cust-001",
			roles: ["admin", "user"],
		},
		...overrides,
	} as unknown as FastifyRequest;
}

describe("createServiceClient", () => {
	const client = createServiceClient("http://notification:5001");

	beforeEach(() => {
		mockFetch.mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	it("propagates tenant headers on GET", async () => {
		const req = createMockRequest();
		await client.get("/api/v1/notifications", req);

		expect(mockFetch).toHaveBeenCalledWith(
			"http://notification:5001/api/v1/notifications",
			expect.objectContaining({
				method: "GET",
				headers: expect.objectContaining({
					"x-gatekeeper-user-id": "user-001",
					"x-gatekeeper-email": "user@example.com",
					"x-gatekeeper-roles": "admin,user",
					"x-customer-id": "cust-001",
					"x-request-id": "req-123",
				}),
			}),
		);
	});

	it("propagates tenant headers on POST with body", async () => {
		const req = createMockRequest();
		await client.post("/api/v1/notifications", { message: "hello" }, req);

		expect(mockFetch).toHaveBeenCalledWith(
			"http://notification:5001/api/v1/notifications",
			expect.objectContaining({
				method: "POST",
				body: JSON.stringify({ message: "hello" }),
				headers: expect.objectContaining({
					"x-customer-id": "cust-001",
					"content-type": "application/json",
				}),
			}),
		);
	});

	it("handles missing tenant gracefully", async () => {
		const req = createMockRequest({ tenant: null } as Partial<FastifyRequest>);
		await client.get("/api/v1/health", req);

		const headers = mockFetch.mock.calls[0][1].headers;
		expect(headers["x-gatekeeper-user-id"]).toBeUndefined();
		expect(headers["x-customer-id"]).toBeUndefined();
	});

	it("handles missing correlation ID gracefully", async () => {
		const req = createMockRequest({ correlationId: undefined } as Partial<FastifyRequest>);
		await client.get("/api/v1/health", req);

		const headers = mockFetch.mock.calls[0][1].headers;
		expect(headers["x-request-id"]).toBeUndefined();
	});

	it("supports PATCH requests", async () => {
		const req = createMockRequest();
		await client.patch("/api/v1/items/123", { name: "updated" }, req);

		expect(mockFetch).toHaveBeenCalledWith(
			"http://notification:5001/api/v1/items/123",
			expect.objectContaining({ method: "PATCH" }),
		);
	});

	it("supports DELETE requests", async () => {
		const req = createMockRequest();
		await client.delete("/api/v1/items/123", req);

		expect(mockFetch).toHaveBeenCalledWith(
			"http://notification:5001/api/v1/items/123",
			expect.objectContaining({ method: "DELETE" }),
		);
	});
});
