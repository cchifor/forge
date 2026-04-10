import type { Prisma } from "@prisma/client";
import { prisma } from "../lib/prisma.js";
import { NotFoundError, AlreadyExistsError } from "../lib/errors.js";
import type { ItemCreate, ItemUpdate, ItemStatus, PaginatedItems } from "../schemas/item.schema.js";
import type { TenantContext } from "../middleware/tenant.js";

interface ListParams {
	tenant: TenantContext;
	skip: number;
	limit: number;
	status?: ItemStatus;
	search?: string;
}

export async function list(params: ListParams): Promise<PaginatedItems> {
	const { tenant, skip, limit, status, search } = params;

	const where: Prisma.ItemWhereInput = { customer_id: tenant.customerId };
	if (status) where.status = status;
	if (search) {
		where.AND = [
			{ customer_id: tenant.customerId },
			{
				OR: [
					{ name: { contains: search, mode: "insensitive" } },
					{ description: { contains: search, mode: "insensitive" } },
				],
			},
		];
		delete where.customer_id;
	}

	const [items, total] = await Promise.all([
		prisma.item.findMany({ where, skip, take: limit, orderBy: { created_at: "desc" } }),
		prisma.item.count({ where }),
	]);

	return { items, total, skip, limit, has_more: skip + items.length < total };
}

export async function create(tenant: TenantContext, data: ItemCreate) {
	const existing = await prisma.item.findFirst({
		where: { name: data.name, customer_id: tenant.customerId },
	});
	if (existing) throw new AlreadyExistsError("Item", data.name);

	return prisma.item.create({
		data: {
			...data,
			customer_id: tenant.customerId,
			user_id: tenant.userId,
		},
	});
}

export async function getById(tenant: TenantContext, id: string) {
	const item = await prisma.item.findFirst({
		where: { id, customer_id: tenant.customerId },
	});
	if (!item) throw new NotFoundError("Item", id);
	return item;
}

export async function update(tenant: TenantContext, id: string, data: ItemUpdate) {
	await getById(tenant, id);

	if (data.name) {
		const existing = await prisma.item.findFirst({
			where: { name: data.name, customer_id: tenant.customerId, NOT: { id } },
		});
		if (existing) throw new AlreadyExistsError("Item", data.name);
	}

	return prisma.item.update({ where: { id }, data });
}

export async function remove(tenant: TenantContext, id: string) {
	await getById(tenant, id);
	await prisma.item.delete({ where: { id } });
}
