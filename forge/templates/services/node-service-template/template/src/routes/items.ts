import type { FastifyInstance } from "fastify";
import { ItemCreate, ItemUpdate, ItemStatus } from "../schemas/item.schema.js";
import { PaginationQuery } from "../schemas/common.schema.js";
import * as itemService from "../services/item.service.js";

export async function itemRoutes(app: FastifyInstance) {
	// Require tenant context for all item routes
	app.addHook("onRequest", async (req, reply) => {
		if (!req.tenant) {
			return reply.code(401).send({ error: "Authentication required" });
		}
	});

	// List items (paginated, with search & status filter)
	app.get("/", async (req, reply) => {
		const query = req.query as Record<string, string>;
		const { skip, limit } = PaginationQuery.parse(query);
		const status = query.status ? ItemStatus.parse(query.status) : undefined;
		const search = query.search || undefined;

		const result = await itemService.list({ tenant: req.tenant!, skip, limit, status, search });
		return reply.send(result);
	});

	// Create item
	app.post("/", async (req, reply) => {
		const data = ItemCreate.parse(req.body);
		const item = await itemService.create(req.tenant!, data);
		return reply.code(201).send(item);
	});

	// Get item by ID
	app.get("/:id", async (req, reply) => {
		const { id } = req.params as { id: string };
		const item = await itemService.getById(req.tenant!, id);
		return reply.send(item);
	});

	// Update item
	app.patch("/:id", async (req, reply) => {
		const { id } = req.params as { id: string };
		const data = ItemUpdate.parse(req.body);
		const item = await itemService.update(req.tenant!, id, data);
		return reply.send(item);
	});

	// Delete item
	app.delete("/:id", async (req, reply) => {
		const { id } = req.params as { id: string };
		await itemService.remove(req.tenant!, id);
		return reply.code(204).send();
	});
}
