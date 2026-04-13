import type { FastifyInstance } from "fastify";

export async function homeRoutes(app: FastifyInstance) {
	app.get("/", async (_req, reply) => {
		return reply.send({ message: "Welcome to the API" });
	});

	app.get("/info", async (_req, reply) => {
		return reply.send({
			name: process.env.npm_package_name ?? "unknown",
			version: process.env.npm_package_version ?? "0.0.0",
			nodeVersion: process.version,
			env: process.env.NODE_ENV ?? "development",
		});
	});
}
