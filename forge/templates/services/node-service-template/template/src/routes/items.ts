import type { FastifyInstance } from "fastify";
import { ItemCreate, ItemUpdate, ItemStatus } from "../schemas/item.schema.js";
import { PaginationQuery } from "../schemas/common.schema.js";
import type { AuthenticatedRequest } from "../middleware/tenant.js";
import * as itemService from "../services/item.service.js";

export async function itemRoutes(app: FastifyInstance) {
	app.get("/", async (req, reply) => {
		const { tenant } = req as AuthenticatedRequest;
		const query = req.query as Record<string, string>;
		const { skip, limit } = PaginationQuery.parse(query);
		const status = query.status ? ItemStatus.parse(query.status) : undefined;
		const search = query.search || undefined;

		const result = await itemService.list({ tenant, skip, limit, status, search });
		return reply.send(result);
	});

	app.post("/", async (req, reply) => {
		const { tenant } = req as AuthenticatedRequest;
		const data = ItemCreate.parse(req.body);
		const item = await itemService.create(tenant, data);
		return reply.code(201).send(item);
	});

	app.get("/:id", async (req, reply) => {
		const { tenant } = req as AuthenticatedRequest;
		const { id } = req.params as { id: string };
		const item = await itemService.getById(tenant, id);
		return reply.send(item);
	});

	app.patch("/:id", async (req, reply) => {
		const { tenant } = req as AuthenticatedRequest;
		const { id } = req.params as { id: string };
		const data = ItemUpdate.parse(req.body);
		const item = await itemService.update(tenant, id, data);
		return reply.send(item);
	});

	app.delete("/:id", async (req, reply) => {
		const { tenant } = req as AuthenticatedRequest;
		const { id } = req.params as { id: string };
		await itemService.remove(tenant, id);
		return reply.code(204).send();
	});
}
