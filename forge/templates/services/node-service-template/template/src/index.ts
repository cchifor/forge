// FORGE:ENTRY_PRELOAD
import "dotenv/config";
import { buildApp } from "./app.js";
import { appConfig } from "./config/index.js";

async function main() {
	const app = await buildApp();
	await app.listen({ port: appConfig.server.port, host: appConfig.server.host });
	console.log(`Server running on ${appConfig.server.host}:${appConfig.server.port}`);

	// Graceful shutdown: drain in-flight requests + close DB/plugin resources
	// on SIGTERM/SIGINT (a rollout sends SIGTERM). Fastify's close() stops
	// accepting new connections and waits for active ones to finish, then runs
	// onClose hooks. Without this, in-flight requests are cut mid-response on
	// every deploy.
	let shuttingDown = false;
	for (const signal of ["SIGTERM", "SIGINT"] as const) {
		process.on(signal, async () => {
			if (shuttingDown) return;
			shuttingDown = true;
			app.log.info(`${signal} received — draining connections`);
			try {
				await app.close();
				process.exit(0);
			} catch (err) {
				app.log.error(err);
				process.exit(1);
			}
		});
	}
}

main().catch((err) => {
	console.error(err);
	process.exit(1);
});
