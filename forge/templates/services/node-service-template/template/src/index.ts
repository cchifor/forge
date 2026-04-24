// FORGE:ENTRY_PRELOAD
import "dotenv/config";
import { buildApp } from "./app.js";
import { appConfig } from "./config/index.js";

async function main() {
	const app = await buildApp();
	await app.listen({ port: appConfig.server.port, host: appConfig.server.host });
	console.log(`Server running on ${appConfig.server.host}:${appConfig.server.port}`);
}

main().catch((err) => {
	console.error(err);
	process.exit(1);
});
