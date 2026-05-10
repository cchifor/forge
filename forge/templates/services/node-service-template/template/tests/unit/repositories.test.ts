import { describe, it, expect, vi } from "vitest";
import { buildIdentity } from "@forge/platform-auth-node";
import { PrismaItemRepository } from "../../src/data/repositories/item-repository.js";

const identity = buildIdentity({
	tenantId: "tenant-1",
	subject: "user-1",
});

interface MockPrismaItem {
	findMany: ReturnType<typeof vi.fn>;
	findFirst: ReturnType<typeof vi.fn>;
	count: ReturnType<typeof vi.fn>;
	create: ReturnType<typeof vi.fn>;
	update: ReturnType<typeof vi.fn>;
	delete: ReturnType<typeof vi.fn>;
}

function makeMock(): MockPrismaItem {
	return {
		findMany: vi.fn(),
		findFirst: vi.fn(),
		count: vi.fn(),
		create: vi.fn(),
		update: vi.fn(),
		delete: vi.fn(),
	};
}

describe("PrismaItemRepository", () => {
	it("scopes list queries by tenantId", async () => {
		const mock = makeMock();
		mock.findMany.mockResolvedValue([]);
		mock.count.mockResolvedValue(0);
		const repo = new PrismaItemRepository(mock as unknown as never);

		await repo.list(identity, { skip: 0, limit: 10 });

		expect(mock.findMany).toHaveBeenCalledWith(
			expect.objectContaining({
				where: expect.objectContaining({ customer_id: "tenant-1" }),
			}),
		);
	});

	it("includes status filter when provided", async () => {
		const mock = makeMock();
		mock.findMany.mockResolvedValue([]);
		mock.count.mockResolvedValue(0);
		const repo = new PrismaItemRepository(mock as unknown as never);

		await repo.list(identity, { status: "ACTIVE" });

		const args = mock.findMany.mock.calls[0][0];
		expect(args.where.status).toBe("ACTIVE");
		expect(args.where.customer_id).toBe("tenant-1");
	});

	it("getById always scopes by customer_id", async () => {
		const mock = makeMock();
		mock.findFirst.mockResolvedValue(null);
		const repo = new PrismaItemRepository(mock as unknown as never);

		await repo.getById(identity, "abc");

		expect(mock.findFirst).toHaveBeenCalledWith({
			where: { customer_id: "tenant-1", id: "abc" },
		});
	});

	it("findByNameExcluding adds NOT id to the where clause", async () => {
		const mock = makeMock();
		mock.findFirst.mockResolvedValue(null);
		const repo = new PrismaItemRepository(mock as unknown as never);

		await repo.findByNameExcluding(identity, "dup", "abc");

		expect(mock.findFirst).toHaveBeenCalledWith({
			where: {
				customer_id: "tenant-1",
				name: "dup",
				NOT: { id: "abc" },
			},
		});
	});

	it("create injects tenant ids into the row", async () => {
		const mock = makeMock();
		mock.create.mockResolvedValue({});
		const repo = new PrismaItemRepository(mock as unknown as never);

		await repo.create(identity, { name: "x" } as never);

		expect(mock.create).toHaveBeenCalledWith({
			data: expect.objectContaining({
				name: "x",
				customer_id: "tenant-1",
				user_id: "user-1",
			}),
		});
	});
});
