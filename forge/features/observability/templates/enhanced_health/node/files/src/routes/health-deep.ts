import type { FastifyInstance } from "fastify";
import {
	checkKeycloak,
	checkRedis,
} from "../services/health-checks.service.js";

export async function healthDeepRoutes(app: FastifyInstance) {
	app.get("/deep", async (_req, reply) => {
		const [redis, keycloak] = await Promise.all([
			checkRedis(),
			checkKeycloak(),
		]);
		const overall = redis.status === "up" && keycloak.status === "up" ? "up" : "down";
		return reply.code(overall === "up" ? 200 : 503).send({
			status: overall,
			components: { redis, keycloak },
		});
	});
}
