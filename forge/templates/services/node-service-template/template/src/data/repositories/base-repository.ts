import type { TenantContext } from "../../middleware/tenant.js";

/**
 * Tenant-aware repository contract.
 *
 * Encapsulates persistence so service-layer code can depend on this
 * interface rather than the Prisma client directly. Lets unit tests
 * stub the data layer (no test database required) and gives operators
 * a single seam to swap ORMs without rewriting business logic.
 *
 * Type parameters:
 * - `TEntity` — the row type returned by the underlying ORM.
 * - `TCreate` — fields the caller supplies when creating.
 * - `TUpdate` — fields the caller may patch.
 *
 * Implementations are responsible for scoping every query by
 * `tenant.customerId` — concrete repos build a tenant `where` clause
 * once in `scopeWhere` (see `PrismaRepository`) so callers can't
 * accidentally bypass isolation.
 */
export interface Repository<TEntity, TCreate, TUpdate> {
	list(
		tenant: TenantContext,
		options?: ListOptions,
	): Promise<{ items: TEntity[]; total: number }>;

	getById(tenant: TenantContext, id: string): Promise<TEntity | null>;

	findByName(tenant: TenantContext, name: string): Promise<TEntity | null>;

	create(tenant: TenantContext, data: TCreate): Promise<TEntity>;

	update(tenant: TenantContext, id: string, data: TUpdate): Promise<TEntity>;

	delete(tenant: TenantContext, id: string): Promise<void>;
}

export interface ListOptions {
	skip?: number;
	limit?: number;
	status?: string;
	search?: string;
	excludeId?: string;
}
