import type { IdentityContext } from "../../types/auth.js";

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
 * `identity.tenantId` — concrete repos build a tenant `where` clause
 * once in `scopeWhere` (see `PrismaRepository`) so callers can't
 * accidentally bypass isolation.
 */
export interface Repository<TEntity, TCreate, TUpdate> {
	list(
		identity: IdentityContext,
		options?: ListOptions,
	): Promise<{ items: TEntity[]; total: number }>;

	getById(identity: IdentityContext, id: string): Promise<TEntity | null>;

	findByName(identity: IdentityContext, name: string): Promise<TEntity | null>;

	create(identity: IdentityContext, data: TCreate): Promise<TEntity>;

	update(identity: IdentityContext, id: string, data: TUpdate): Promise<TEntity>;

	delete(identity: IdentityContext, id: string): Promise<void>;
}

export interface ListOptions {
	skip?: number;
	limit?: number;
	status?: string;
	search?: string;
	excludeId?: string;
}
