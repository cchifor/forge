import { describe, it, expect, vi, beforeAll, afterAll, beforeEach } from "vitest";
import { buildApp } from "../../src/app.js";
import { prisma } from "../../src/lib/prisma.js";
import type { FastifyInstance } from "fastify";

vi.mock("../../src/lib/prisma.js", () => ({
	prisma: {
		item: {
			findMany: vi.fn(),
			findFirst: vi.fn(),
			findUnique: vi.fn(),
			create: vi.fn(),
			update: vi.fn(),
			delete: vi.fn(),
			count: vi.fn(),
		},
		$queryRaw: vi.fn(),
		$disconnect: vi.fn(),
	},
}));

const mockItem = {
	id: "550e8400-e29b-41d4-a716-446655440000",
	name: "Test Item",
	description: null,
	tags: [],
	status: "DRAFT" as const,
	createdAt: new Date("2024-01-01"),
	updatedAt: new Date("2024-01-01"),
};

let app: FastifyInstance;

beforeAll(async () => {
	app = await buildApp();
});

afterAll(async () => {
	await app.close();
});

beforeEach(() => {
	vi.clearAllMocks();
});

describe("Item CRUD endpoints", () => {
	describe("GET /api/v1/items", () => {
		it("returns paginated items", async () => {
			vi.mocked(prisma.item.findMany).mockResolvedValue([mockItem]);
			vi.mocked(prisma.item.count).mockResolvedValue(1);

			const res = await app.inject({ method: "GET", url: "/api/v1/items" });
			expect(res.statusCode).toBe(200);

			const body = JSON.parse(res.payload);
			expect(body.items).toHaveLength(1);
			expect(body.total).toBe(1);
		});

		it("supports status filter", async () => {
			vi.mocked(prisma.item.findMany).mockResolvedValue([]);
			vi.mocked(prisma.item.count).mockResolvedValue(0);

			const res = await app.inject({
				method: "GET",
				url: "/api/v1/items?status=ACTIVE",
			});
			expect(res.statusCode).toBe(200);
		});
	});

	describe("POST /api/v1/items", () => {
		it("creates an item", async () => {
			vi.mocked(prisma.item.findFirst).mockResolvedValue(null);
			vi.mocked(prisma.item.create).mockResolvedValue(mockItem);

			const res = await app.inject({
				method: "POST",
				url: "/api/v1/items",
				payload: { name: "Test Item" },
			});
			expect(res.statusCode).toBe(201);

			const body = JSON.parse(res.payload);
			expect(body.name).toBe("Test Item");
		});

		it("returns 409 for duplicate name", async () => {
			vi.mocked(prisma.item.findFirst).mockResolvedValue(mockItem);

			const res = await app.inject({
				method: "POST",
				url: "/api/v1/items",
				payload: { name: "Test Item" },
			});
			expect(res.statusCode).toBe(409);
		});
	});

	describe("GET /api/v1/items/:id", () => {
		it("returns item by ID", async () => {
			vi.mocked(prisma.item.findUnique).mockResolvedValue(mockItem);

			const res = await app.inject({
				method: "GET",
				url: `/api/v1/items/${mockItem.id}`,
			});
			expect(res.statusCode).toBe(200);

			const body = JSON.parse(res.payload);
			expect(body.id).toBe(mockItem.id);
		});

		it("returns 404 when not found", async () => {
			vi.mocked(prisma.item.findUnique).mockResolvedValue(null);

			const res = await app.inject({
				method: "GET",
				url: "/api/v1/items/nonexistent",
			});
			expect(res.statusCode).toBe(404);
		});
	});

	describe("PATCH /api/v1/items/:id", () => {
		it("updates an item", async () => {
			const updated = { ...mockItem, name: "Updated" };
			vi.mocked(prisma.item.findUnique).mockResolvedValue(mockItem);
			vi.mocked(prisma.item.findFirst).mockResolvedValue(null);
			vi.mocked(prisma.item.update).mockResolvedValue(updated);

			const res = await app.inject({
				method: "PATCH",
				url: `/api/v1/items/${mockItem.id}`,
				payload: { name: "Updated" },
			});
			expect(res.statusCode).toBe(200);

			const body = JSON.parse(res.payload);
			expect(body.name).toBe("Updated");
		});
	});

	describe("DELETE /api/v1/items/:id", () => {
		it("deletes an item", async () => {
			vi.mocked(prisma.item.findUnique).mockResolvedValue(mockItem);
			vi.mocked(prisma.item.delete).mockResolvedValue(mockItem);

			const res = await app.inject({
				method: "DELETE",
				url: `/api/v1/items/${mockItem.id}`,
			});
			expect(res.statusCode).toBe(204);
		});

		it("returns 404 when item does not exist", async () => {
			vi.mocked(prisma.item.findUnique).mockResolvedValue(null);

			const res = await app.inject({
				method: "DELETE",
				url: "/api/v1/items/nonexistent",
			});
			expect(res.statusCode).toBe(404);
		});
	});
});
