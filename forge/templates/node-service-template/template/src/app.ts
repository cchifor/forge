import Fastify from "fastify";
import cors from "@fastify/cors";
import { healthRoutes } from "./routes/health.js";
import { homeRoutes } from "./routes/home.js";
import { itemRoutes } from "./routes/items.js";
import { errorHandler } from "./middleware/error-handler.js";
import { correlationHook } from "./middleware/correlation.js";
import { requestLogger } from "./middleware/logging.js";

export async function buildApp() {
	const app = Fastify({ logger: true });

	await app.register(cors);

	app.addHook("onRequest", correlationHook);
	app.addHook("onResponse", requestLogger);
	app.setErrorHandler(errorHandler);

	await app.register(homeRoutes, { prefix: "/api/v1" });
	await app.register(healthRoutes, { prefix: "/api/v1/health" });
	await app.register(itemRoutes, { prefix: "/api/v1/items" });

	return app;
}
