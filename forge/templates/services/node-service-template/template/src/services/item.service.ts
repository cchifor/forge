import { AlreadyExistsError, NotFoundError } from "../lib/errors.js";
import {
	itemRepository,
	type PrismaItemRepository,
} from "../data/repositories/index.js";
import type { TenantContext } from "../middleware/tenant.js";
import type {
	ItemCreate,
	ItemStatus,
	ItemUpdate,
	PaginatedItems,
} from "../schemas/item.schema.js";

interface ListParams {
	tenant: TenantContext;
	skip: number;
	limit: number;
	status?: ItemStatus;
	search?: string;
}

/**
 * Service layer.
 *
 * Depends on :class:`PrismaItemRepository` only via the
 * :class:`Repository` interface — tests can substitute an in-memory
 * implementation without touching the database. The default export
 * uses the repository singleton; ``itemService.withRepository(repo)``
 * builds a service bound to a custom repo for tests.
 */

function buildService(repo: PrismaItemRepository = itemRepository) {
	return {
		async list(params: ListParams): Promise<PaginatedItems> {
			const { tenant, skip, limit, status, search } = params;
			const { items, total } = await repo.list(tenant, {
				skip,
				limit,
				status,
				search,
			});
			return {
				items,
				total,
				skip,
				limit,
				has_more: skip + items.length < total,
			};
		},

		async create(tenant: TenantContext, data: ItemCreate) {
			const existing = await repo.findByName(tenant, data.name);
			if (existing) throw new AlreadyExistsError("Item", data.name);
			return repo.create(tenant, data);
		},

		async getById(tenant: TenantContext, id: string) {
			const item = await repo.getById(tenant, id);
			if (!item) throw new NotFoundError("Item", id);
			return item;
		},

		async update(tenant: TenantContext, id: string, data: ItemUpdate) {
			await this.getById(tenant, id);
			if (data.name) {
				const existing = await repo.findByNameExcluding(tenant, data.name, id);
				if (existing) throw new AlreadyExistsError("Item", data.name);
			}
			return repo.update(tenant, id, data);
		},

		async remove(tenant: TenantContext, id: string) {
			await this.getById(tenant, id);
			await repo.delete(tenant, id);
		},

		withRepository(other: PrismaItemRepository) {
			return buildService(other);
		},
	};
}

const itemService = buildService();

export const list = itemService.list.bind(itemService);
export const create = itemService.create.bind(itemService);
export const getById = itemService.getById.bind(itemService);
export const update = itemService.update.bind(itemService);
export const remove = itemService.remove.bind(itemService);
export const withRepository = itemService.withRepository.bind(itemService);
