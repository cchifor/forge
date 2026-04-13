import { describe, it, expect, beforeAll, afterAll } from "vitest";
import Fastify, { type FastifyInstance } from "fastify";
import { tenantHook } from "../../src/middleware/tenant.js";

let app: FastifyInstance;

beforeAll(async () => {
	app = Fastify();
	app.addHook("onRequest", tenantHook);
	app.get("/test", async (req) => ({
		tenant: req.tenant,
	}));
	await app.ready();
});

afterAll(async () => {
	await app.close();
});

describe("tenantHook middleware", () => {
	it("extracts tenant from X-Gatekeeper-* headers", async () => {
		const res = await app.inject({
			method: "GET",
			url: "/test",
			headers: {
				"x-gatekeeper-user-id": "user-123",
				"x-gatekeeper-email": "test@example.com",
				"x-gatekeeper-roles": "admin,user",
			},
		});

		const body = JSON.parse(res.payload);
		expect(body.tenant).toEqual({
			userId: "user-123",
			email: "test@example.com",
			customerId: "user-123", // defaults to userId
			roles: ["admin", "user"],
		});
	});

	it("uses x-customer-id for S2S tenant propagation", async () => {
		const res = await app.inject({
			method: "GET",
			url: "/test",
			headers: {
				"x-gatekeeper-user-id": "service-account",
				"x-gatekeeper-email": "svc@internal",
				"x-customer-id": "tenant-abc",
			},
		});

		const body = JSON.parse(res.payload);
		expect(body.tenant.customerId).toBe("tenant-abc");
		expect(body.tenant.userId).toBe("service-account");
	});

	it("sets tenant to null when headers are missing", async () => {
		const res = await app.inject({
			method: "GET",
			url: "/test",
		});

		const body = JSON.parse(res.payload);
		expect(body.tenant).toBeNull();
	});

	it("parses empty roles as empty array", async () => {
		const res = await app.inject({
			method: "GET",
			url: "/test",
			headers: {
				"x-gatekeeper-user-id": "user-123",
				"x-gatekeeper-roles": "",
			},
		});

		const body = JSON.parse(res.payload);
		expect(body.tenant.roles).toEqual([]);
	});
});
