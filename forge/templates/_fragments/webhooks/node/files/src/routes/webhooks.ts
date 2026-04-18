import type { FastifyInstance } from "fastify";
import {
	createWebhook,
	deleteWebhook,
	deliver,
	getWebhook,
	listWebhooks,
	type WebhookCreate,
} from "../services/webhook.service.js";

export async function webhookRoutes(app: FastifyInstance) {
	app.get("/", async () => {
		return { webhooks: listWebhooks() };
	});

	app.post("/", async (req, reply) => {
		const body = req.body as WebhookCreate;
		if (!body || !body.name || !body.url) {
			return reply
				.code(400)
				.send({ detail: "name and url are required" });
		}
		const webhook = createWebhook(body);
		return reply.code(201).send(webhook);
	});

	app.delete("/:id", async (req, reply) => {
		const { id } = req.params as { id: string };
		const ok = deleteWebhook(id);
		return reply.code(ok ? 204 : 404).send();
	});

	app.post("/:id/test", async (req, reply) => {
		const { id } = req.params as { id: string };
		const webhook = getWebhook(id);
		if (!webhook) {
			return reply.code(404).send({ detail: "webhook not found" });
		}
		const result = await deliver(webhook, "webhook.test", {
			message: "forge webhook test",
		});
		return reply.send(result);
	});
}
