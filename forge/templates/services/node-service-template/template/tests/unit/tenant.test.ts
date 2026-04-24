import { describe, it, expect, beforeAll, afterAll } from "vitest";
import Fastify, { type FastifyInstance } from "fastify";
import {
	tenantHook,
	requireTenant,
	type AuthenticatedRequest,
} from "../../src/middleware/tenant.js";

let app: FastifyInstance;

beforeAll(async () => {
	app = Fastify();
	app.addHook("onRequest", tenantHook);

	app.get("/public/test", async (req) => ({ tenant: req.tenant }));

	await app.register(async (auth) => {
		auth.addHook("preHandler", requireTenant);
		auth.get("/protected/test", async (req) => {
			const { tenant } = req as AuthenticatedRequest;
			return { tenant };
		});
	});

	await app.ready();
});

afterAll(async () => {
	await app.close();
});

describe("tenantHook middleware", () => {
	it("extracts tenant from X-Gatekeeper-* headers", async () => {
		const res = await app.inject({
			method: "GET",
			url: "/public/test",
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
			customerId: "user-123",
			roles: ["admin", "user"],
		});
	});

	it("uses x-customer-id for S2S tenant propagation", async () => {
		const res = await app.inject({
			method: "GET",
			url: "/public/test",
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
		const res = await app.inject({ method: "GET", url: "/public/test" });

		const body = JSON.parse(res.payload);
		expect(body.tenant).toBeNull();
	});

	it("parses empty roles as empty array", async () => {
		const res = await app.inject({
			method: "GET",
			url: "/public/test",
			headers: {
				"x-gatekeeper-user-id": "user-123",
				"x-gatekeeper-roles": "",
			},
		});

		const body = JSON.parse(res.payload);
		expect(body.tenant.roles).toEqual([]);
	});
});

describe("requireTenant preHandler", () => {
	it("returns 401 with AUTH_REQUIRED when tenant is missing", async () => {
		const res = await app.inject({ method: "GET", url: "/protected/test" });
		expect(res.statusCode).toBe(401);
		const body = JSON.parse(res.payload);
		expect(body.code).toBe("AUTH_REQUIRED");
	});

	it("allows the request through when tenant headers are present", async () => {
		const res = await app.inject({
			method: "GET",
			url: "/protected/test",
			headers: {
				"x-gatekeeper-user-id": "user-123",
				"x-gatekeeper-email": "test@example.com",
			},
		});
		expect(res.statusCode).toBe(200);
		const body = JSON.parse(res.payload);
		expect(body.tenant.userId).toBe("user-123");
	});

	it("does not affect sibling routes outside the authenticated scope", async () => {
		const res = await app.inject({ method: "GET", url: "/public/test" });
		expect(res.statusCode).toBe(200);
	});
});
