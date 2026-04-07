import type { Prisma } from "@prisma/client";
import { prisma } from "../lib/prisma.js";
import { NotFoundError, AlreadyExistsError } from "../lib/errors.js";
import type { ItemCreate, ItemUpdate, ItemStatus, PaginatedItems } from "../schemas/item.schema.js";

interface ListParams {
	skip: number;
	limit: number;
	status?: ItemStatus;
	search?: string;
}

export async function list(params: ListParams): Promise<PaginatedItems> {
	const { skip, limit, status, search } = params;

	const where: Prisma.ItemWhereInput = {};
	if (status) where.status = status;
	if (search) {
		where.OR = [
			{ name: { contains: search, mode: "insensitive" } },
			{ description: { contains: search, mode: "insensitive" } },
		];
	}

	const [items, total] = await Promise.all([
		prisma.item.findMany({ where, skip, take: limit, orderBy: { createdAt: "desc" } }),
		prisma.item.count({ where }),
	]);

	return { items, total, skip, limit };
}

export async function create(data: ItemCreate) {
	const existing = await prisma.item.findFirst({ where: { name: data.name } });
	if (existing) throw new AlreadyExistsError("Item", data.name);

	return prisma.item.create({ data });
}

export async function getById(id: string) {
	const item = await prisma.item.findUnique({ where: { id } });
	if (!item) throw new NotFoundError("Item", id);
	return item;
}

export async function update(id: string, data: ItemUpdate) {
	await getById(id);

	if (data.name) {
		const existing = await prisma.item.findFirst({
			where: { name: data.name, NOT: { id } },
		});
		if (existing) throw new AlreadyExistsError("Item", data.name);
	}

	return prisma.item.update({ where: { id }, data });
}

export async function remove(id: string) {
	await getById(id);
	await prisma.item.delete({ where: { id } });
}
