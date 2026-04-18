/**
 * BullMQ worker entrypoint.
 *
 * Run with `npm run worker` (add "worker": "node --loader ts-node/esm src/worker/worker.ts"
 * to package.json scripts for dev; for production compile to dist/ and run
 * `node dist/worker/worker.js`).
 *
 * Define job handlers in this file — each `case` in the switch dispatches on
 * job name. Jobs are enqueued with `taskQueue.add('<name>', payload)` from
 * any route handler.
 */

import { Worker } from "bullmq";
import { connection } from "./queue.js";

const worker = new Worker(
	"forge-tasks",
	async (job) => {
		switch (job.name) {
			case "hello": {
				const { name } = job.data as { name: string };
				const message = `hello, ${name}`;
				console.log("[worker] hello:", message);
				return message;
			}
			default:
				throw new Error(`unknown job: ${job.name}`);
		}
	},
	{ connection },
);

worker.on("failed", (job, err) => {
	console.error(`[worker] job ${job?.id} failed:`, err);
});

worker.on("completed", (job) => {
	console.log(`[worker] job ${job.id} completed`);
});

const shutdown = async () => {
	console.log("[worker] shutting down ...");
	await worker.close();
	await connection.quit();
	process.exit(0);
};

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
