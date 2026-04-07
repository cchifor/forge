import { describe, it, expect, vi, beforeEach } from "vitest";
import { prisma } from "../../src/lib/prisma.js";
import * as itemService from "../../src/services/item.service.js";
import { NotFoundError, AlreadyExistsError } from "../../src/lib/errors.js";

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
	},
}));

const mockItem = {
	id: "550e8400-e29b-41d4-a716-446655440000",
	name: "Test Item",
	description: null,
	tags: [],
	status: "DRAFT" as const,
	createdAt: new Date(),
	updatedAt: new Date(),
};

describe("ItemService", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe("list", () => {
		it("returns paginated items", async () => {
			vi.mocked(prisma.item.findMany).mockResolvedValue([mockItem]);
			vi.mocked(prisma.item.count).mockResolvedValue(1);

			const result = await itemService.list({ skip: 0, limit: 50 });

			expect(result.items).toHaveLength(1);
			expect(result.total).toBe(1);
			expect(result.skip).toBe(0);
			expect(result.limit).toBe(50);
		});

		it("applies status filter", async () => {
			vi.mocked(prisma.item.findMany).mockResolvedValue([]);
			vi.mocked(prisma.item.count).mockResolvedValue(0);

			await itemService.list({ skip: 0, limit: 50, status: "ACTIVE" });

			expect(prisma.item.findMany).toHaveBeenCalledWith(
				expect.objectContaining({
					where: expect.objectContaining({ status: "ACTIVE" }),
				}),
			);
		});
	});

	describe("create", () => {
		it("creates an item when name is unique", async () => {
			vi.mocked(prisma.item.findFirst).mockResolvedValue(null);
			vi.mocked(prisma.item.create).mockResolvedValue(mockItem);

			const result = await itemService.create({
				name: "Test Item",
				tags: [],
				status: "DRAFT",
			});

			expect(result).toEqual(mockItem);
		});

		it("throws AlreadyExistsError for duplicate name", async () => {
			vi.mocked(prisma.item.findFirst).mockResolvedValue(mockItem);

			await expect(
				itemService.create({ name: "Test Item", tags: [], status: "DRAFT" }),
			).rejects.toThrow(AlreadyExistsError);
		});
	});

	describe("getById", () => {
		it("returns item when found", async () => {
			vi.mocked(prisma.item.findUnique).mockResolvedValue(mockItem);
			const result = await itemService.getById(mockItem.id);
			expect(result).toEqual(mockItem);
		});

		it("throws NotFoundError when not found", async () => {
			vi.mocked(prisma.item.findUnique).mockResolvedValue(null);
			await expect(itemService.getById("nonexistent")).rejects.toThrow(NotFoundError);
		});
	});

	describe("update", () => {
		it("updates an item", async () => {
			const updated = { ...mockItem, name: "Updated" };
			vi.mocked(prisma.item.findUnique).mockResolvedValue(mockItem);
			vi.mocked(prisma.item.findFirst).mockResolvedValue(null);
			vi.mocked(prisma.item.update).mockResolvedValue(updated);

			const result = await itemService.update(mockItem.id, { name: "Updated" });
			expect(result.name).toBe("Updated");
		});
	});

	describe("remove", () => {
		it("deletes an existing item", async () => {
			vi.mocked(prisma.item.findUnique).mockResolvedValue(mockItem);
			vi.mocked(prisma.item.delete).mockResolvedValue(mockItem);

			await expect(itemService.remove(mockItem.id)).resolves.not.toThrow();
		});

		it("throws NotFoundError when item does not exist", async () => {
			vi.mocked(prisma.item.findUnique).mockResolvedValue(null);
			await expect(itemService.remove("nonexistent")).rejects.toThrow(NotFoundError);
		});
	});
});
