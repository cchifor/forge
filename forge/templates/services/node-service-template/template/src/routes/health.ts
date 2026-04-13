import type { FastifyInstance } from "fastify";
import { checkDatabase } from "../services/health.service.js";

export async function healthRoutes(app: FastifyInstance) {
	app.get("/live", async (_req, reply) => {
		return reply.send({ status: "UP", details: "Service is running" });
	});

	app.get("/ready", async (_req, reply) => {
		const db = await checkDatabase();
		const overall = db.status === "UP" ? "UP" : "DOWN";

		return reply.code(overall === "UP" ? 200 : 503).send({
			status: overall,
			components: { database: db },
			system_info: {
				node_version: process.version,
				platform: process.platform,
			},
		});
	});
}
