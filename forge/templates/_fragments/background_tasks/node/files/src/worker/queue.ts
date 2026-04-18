/**
 * BullMQ queue + connection for Node services.
 *
 * Jobs are enqueued from request handlers (`await taskQueue.add('hello', payload)`)
 * and consumed by the worker process started from `src/worker/worker.ts`.
 * Queue and worker share a Redis connection set by `TASKIQ_BROKER_URL`
 * (reusing the env var name from the Python Taskiq feature keeps
 * multi-backend projects consistent).
 */

import { Queue } from "bullmq";
import { Redis } from "ioredis";

const connectionUrl =
	process.env.TASKIQ_BROKER_URL ?? "redis://redis:6379/2";

export const connection = new Redis(connectionUrl, {
	maxRetriesPerRequest: null,
	enableReadyCheck: false,
});

export const taskQueue = new Queue("forge-tasks", { connection });
