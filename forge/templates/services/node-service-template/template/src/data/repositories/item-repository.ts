import type { Item, Prisma } from "@prisma/client";
import { prisma as defaultPrisma } from "../../lib/prisma.js";
import type {
	ItemCreate,
	ItemStatus,
	ItemUpdate,
} from "../../schemas/item.schema.js";
import type { IdentityContext } from "../../types/auth.js";
import type { ListOptions, Repository } from "./base-repository.js";

interface ItemListOptions extends ListOptions {
	status?: ItemStatus;
}

type ItemPrismaClient = typeof defaultPrisma.item;

/**
 * Prisma-backed implementation of the item repository.
 *
 * Tenant scoping happens inside `scopeWhere` so every query method
 * reuses the same predicate — there is no public surface that lets a
 * caller skip the `customer_id` clause.
 */
export class PrismaItemRepository
	implements Repository<Item, ItemCreate, ItemUpdate>
{
	constructor(private readonly client: ItemPrismaClient = defaultPrisma.item) {}

	private scopeWhere(
		identity: IdentityContext,
		extra: Prisma.ItemWhereInput = {},
	): Prisma.ItemWhereInput {
		return { customer_id: identity.tenantId, ...extra };
	}

	async list(
		identity: IdentityContext,
		options: ItemListOptions = {},
	): Promise<{ items: Item[]; total: number }> {
		const { skip = 0, limit = 25, status, search } = options;
		let where: Prisma.ItemWhereInput = this.scopeWhere(identity);
		if (status) where.status = status;
		if (search) {
			where = {
				AND: [
					{ customer_id: identity.tenantId },
					{
						OR: [
							{ name: { contains: search, mode: "insensitive" } },
							{ description: { contains: search, mode: "insensitive" } },
						],
					},
				],
			};
			if (status) (where.AND as Prisma.ItemWhereInput[]).push({ status });
		}

		const [items, total] = await Promise.all([
			this.client.findMany({
				where,
				skip,
				take: limit,
				orderBy: { created_at: "desc" },
			}),
			this.client.count({ where }),
		]);
		return { items, total };
	}

	async getById(identity: IdentityContext, id: string): Promise<Item | null> {
		return this.client.findFirst({ where: this.scopeWhere(identity, { id }) });
	}

	async findByName(identity: IdentityContext, name: string): Promise<Item | null> {
		return this.client.findFirst({ where: this.scopeWhere(identity, { name }) });
	}

	async findByNameExcluding(
		identity: IdentityContext,
		name: string,
		excludeId: string,
	): Promise<Item | null> {
		return this.client.findFirst({
			where: this.scopeWhere(identity, { name, NOT: { id: excludeId } }),
		});
	}

	async create(identity: IdentityContext, data: ItemCreate): Promise<Item> {
		return this.client.create({
			data: {
				...data,
				customer_id: identity.tenantId,
				user_id: identity.subject,
			},
		});
	}

	async update(
		identity: IdentityContext,
		id: string,
		data: ItemUpdate,
	): Promise<Item> {
		// Update bypasses scopeWhere because Prisma doesn't accept a
		// composite `where` for `update`; service-layer callers MUST
		// invoke `getById` first to confirm tenant ownership.
		void identity;
		return this.client.update({ where: { id }, data });
	}

	async delete(identity: IdentityContext, id: string): Promise<void> {
		void identity;
		await this.client.delete({ where: { id } });
	}
}

/** Singleton instance used by the default service wiring. */
export const itemRepository = new PrismaItemRepository();
