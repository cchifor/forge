import { describe, it, expect, vi, beforeEach } from "vitest";
import { prisma } from "../../src/lib/prisma.js";
import * as itemService from "../../src/services/item.service.js";
import { NotFoundError, AlreadyExistsError } from "../../src/lib/errors.js";
import type { TenantContext } from "../../src/middleware/tenant.js";

vi.mock("../../src/lib/prisma.js", () => ({
	prisma: {
		item: {
			findMany: vi.fn(),
			findFirst: vi.fn(),
			create: vi.fn(),
			update: vi.fn(),
			delete: vi.fn(),
			count: vi.fn(),
		},
	},
}));

const tenant: TenantContext = {
	userId: "00000000-0000-0000-0000-000000000001",
	email: "test@localhost",
	customerId: "00000000-0000-0000-0000-000000000001",
	roles: ["user", "admin"],
};

const mockItem = {
	id: "550e8400-e29b-41d4-a716-446655440000",
	customer_id: tenant.customerId,
	user_id: tenant.userId,
	name: "Test Item",
	description: null,
	tags: [],
	status: "DRAFT" as const,
	created_at: new Date(),
	updated_at: new Date(),
};

describe("ItemService", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe("list", () => {
		it("returns paginated items scoped to tenant", async () => {
			vi.mocked(prisma.item.findMany).mockResolvedValue([mockItem]);
			vi.mocked(prisma.item.count).mockResolvedValue(1);

			const result = await itemService.list({ tenant, skip: 0, limit: 50 });

			expect(result.items).toHaveLength(1);
			expect(result.total).toBe(1);
			expect(prisma.item.findMany).toHaveBeenCalledWith(
				expect.objectContaining({
					where: expect.objectContaining({ customer_id: tenant.customerId }),
				}),
			);
		});

		it("applies status filter within tenant scope", async () => {
			vi.mocked(prisma.item.findMany).mockResolvedValue([]);
			vi.mocked(prisma.item.count).mockResolvedValue(0);

			await itemService.list({ tenant, skip: 0, limit: 50, status: "ACTIVE" });

			expect(prisma.item.findMany).toHaveBeenCalledWith(
				expect.objectContaining({
					where: expect.objectContaining({
						customer_id: tenant.customerId,
						status: "ACTIVE",
					}),
				}),
			);
		});
	});

	describe("create", () => {
		it("creates item with tenant context auto-injected", async () => {
			vi.mocked(prisma.item.findFirst).mockResolvedValue(null);
			vi.mocked(prisma.item.create).mockResolvedValue(mockItem);

			const result = await itemService.create(tenant, {
				name: "Test Item",
				tags: [],
				status: "DRAFT",
			});

			expect(result).toEqual(mockItem);
			expect(prisma.item.create).toHaveBeenCalledWith(
				expect.objectContaining({
					data: expect.objectContaining({
						customer_id: tenant.customerId,
						user_id: tenant.userId,
						name: "Test Item",
					}),
				}),
			);
		});

		it("checks duplicate name within same tenant only", async () => {
			vi.mocked(prisma.item.findFirst).mockResolvedValue(mockItem);

			await expect(
				itemService.create(tenant, { name: "Test Item", tags: [], status: "DRAFT" }),
			).rejects.toThrow(AlreadyExistsError);

			// Verify duplicate check includes customerId
			expect(prisma.item.findFirst).toHaveBeenCalledWith(
				expect.objectContaining({
					where: { name: "Test Item", customer_id: tenant.customerId },
				}),
			);
		});
	});

	describe("getById", () => {
		it("returns item scoped to tenant", async () => {
			vi.mocked(prisma.item.findFirst).mockResolvedValue(mockItem);

			const result = await itemService.getById(tenant, mockItem.id);

			expect(result).toEqual(mockItem);
			expect(prisma.item.findFirst).toHaveBeenCalledWith(
				expect.objectContaining({
					where: { id: mockItem.id, customer_id: tenant.customerId },
				}),
			);
		});

		it("throws NotFoundError when item belongs to different tenant", async () => {
			vi.mocked(prisma.item.findFirst).mockResolvedValue(null);

			await expect(itemService.getById(tenant, "other-id")).rejects.toThrow(NotFoundError);
		});
	});

	describe("update", () => {
		it("updates item within tenant scope", async () => {
			const updated = { ...mockItem, name: "Updated" };
			vi.mocked(prisma.item.findFirst).mockResolvedValueOnce(mockItem); // getById
			vi.mocked(prisma.item.findFirst).mockResolvedValueOnce(null); // dupe check
			vi.mocked(prisma.item.update).mockResolvedValue(updated);

			const result = await itemService.update(tenant, mockItem.id, { name: "Updated" });
			expect(result.name).toBe("Updated");
		});

		it("checks duplicate name within same tenant on update", async () => {
			const duplicate = { ...mockItem, id: "other-id" };
			vi.mocked(prisma.item.findFirst).mockResolvedValueOnce(mockItem); // getById
			vi.mocked(prisma.item.findFirst).mockResolvedValueOnce(duplicate); // dupe check

			await expect(
				itemService.update(tenant, mockItem.id, { name: "Taken" }),
			).rejects.toThrow(AlreadyExistsError);
		});
	});

	describe("remove", () => {
		it("deletes item within tenant scope", async () => {
			vi.mocked(prisma.item.findFirst).mockResolvedValue(mockItem);
			vi.mocked(prisma.item.delete).mockResolvedValue(mockItem);

			await expect(itemService.remove(tenant, mockItem.id)).resolves.not.toThrow();
		});

		it("throws NotFoundError for item not in tenant", async () => {
			vi.mocked(prisma.item.findFirst).mockResolvedValue(null);

			await expect(itemService.remove(tenant, "nonexistent")).rejects.toThrow(NotFoundError);
		});
	});
});
