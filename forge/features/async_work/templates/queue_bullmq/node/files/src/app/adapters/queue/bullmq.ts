/**
 * BullMQ queue adapter — concrete ``QueuePort`` implementation backed by
 * BullMQ + ioredis. Per-topic ``Queue`` and ``Worker`` instances are
 * lazily constructed and cached on the adapter.
 *
 * Delivery: at-least-once. BullMQ tracks retries via job options
 * (``attempts`` + back-off). Calling ``nack({requeue: true})`` retries
 * via BullMQ's retry mechanism; ``requeue: false`` marks the job as
 * permanently failed (it lands in BullMQ's failed-jobs store, which
 * doubles as a DLQ).
 *
 * The ``topic`` parameter is the BullMQ queue name. ``delaySeconds`` is
 * passed straight through to BullMQ's job options (native support).
 */

import { Queue, Worker, type Job, type JobsOptions } from "bullmq";
import { Redis } from "ioredis";

import type {
	AckArgs,
	ConsumeArgs,
	EnqueueArgs,
	NackArgs,
	QueueMessage,
	QueuePort,
} from "../../ports/queue.js";

// Reuses the env-var convention from the background_tasks fragment so
// multi-backend projects share one Redis URL across Taskiq / BullMQ /
// Apalis workers.
const DEFAULT_BROKER_URL = "redis://redis:6379/2";

export class BullmqQueueAdapter implements QueuePort {
	private readonly connection: Redis;
	private readonly queues = new Map<string, Queue>();
	// Map of receipt -> Job kept for ack/nack resolution. BullMQ jobs
	// carry their own retry state; we hold the reference so a consumer
	// can call ``adapter.ack({topic, receipt})`` without re-fetching
	// from Redis.
	private readonly inflight = new Map<string, Job>();

	constructor(url: string = process.env.TASKIQ_BROKER_URL ?? DEFAULT_BROKER_URL) {
		this.connection = new Redis(url, {
			maxRetriesPerRequest: null,
			enableReadyCheck: false,
		});
	}

	private queueFor(topic: string): Queue {
		const existing = this.queues.get(topic);
		if (existing) {
			return existing;
		}
		const q = new Queue(topic, { connection: this.connection });
		this.queues.set(topic, q);
		return q;
	}

	async enqueue(args: EnqueueArgs): Promise<string> {
		const { topic, body, delaySeconds = 0 } = args;
		const opts: JobsOptions = {};
		if (delaySeconds > 0) {
			opts.delay = delaySeconds * 1000;
		}
		const job = await this.queueFor(topic).add(topic, body, opts);
		return String(job.id);
	}

	consume(args: ConsumeArgs): AsyncIterable<QueueMessage> {
		const { topic, batchSize = 1 } = args;
		const connection = this.connection;
		const inflight = this.inflight;

		// BullMQ exposes a push-based ``Worker`` rather than a pull-based
		// iterator. Bridge to an AsyncIterable by buffering jobs through
		// an internal queue and resolving the next ``next()`` call as
		// jobs arrive.
		const buffer: QueueMessage[] = [];
		const waiters: Array<(msg: IteratorResult<QueueMessage>) => void> = [];
		let closed = false;

		const worker = new Worker(
			topic,
			async (job) => {
				const receipt = String(job.id);
				inflight.set(receipt, job);
				const msg: QueueMessage = {
					id: receipt,
					body: job.data as Record<string, unknown>,
					receipt,
				};
				const waiter = waiters.shift();
				if (waiter) {
					waiter({ value: msg, done: false });
				} else {
					buffer.push(msg);
				}
				// Returning a promise that never resolves keeps the job
				// in the "active" state until the consumer calls
				// ``ack``/``nack``. BullMQ's stalled-job reaper will
				// re-deliver if the process dies before either is called.
				return new Promise(() => {});
			},
			{ connection, concurrency: batchSize },
		);

		const iterator: AsyncIterator<QueueMessage> = {
			next: () => {
				if (closed) {
					return Promise.resolve({ value: undefined, done: true });
				}
				const buffered = buffer.shift();
				if (buffered) {
					return Promise.resolve({ value: buffered, done: false });
				}
				return new Promise((resolve) => waiters.push(resolve));
			},
			return: async () => {
				closed = true;
				while (waiters.length > 0) {
					const w = waiters.shift();
					if (w) {
						w({ value: undefined, done: true });
					}
				}
				await worker.close();
				return { value: undefined, done: true };
			},
		};

		return {
			[Symbol.asyncIterator]: () => iterator,
		};
	}

	async ack(args: AckArgs): Promise<void> {
		const job = this.inflight.get(args.receipt);
		if (!job) {
			return;
		}
		// Mark the BullMQ job as completed. The worker's stalled-job
		// reaper drops the active marker once ``moveToCompleted`` runs.
		await job.moveToCompleted("acked", job.token ?? "", false);
		this.inflight.delete(args.receipt);
	}

	async nack(args: NackArgs): Promise<void> {
		const job = this.inflight.get(args.receipt);
		if (!job) {
			return;
		}
		const { requeue = true } = args;
		if (requeue) {
			await job.moveToFailed(new Error("nack: requeue"), job.token ?? "", true);
		} else {
			// requeue=false → DLQ semantics. BullMQ's failed-jobs store
			// is the canonical DLQ; drain via the BullMQ admin UI or a
			// scheduled clean-up worker.
			await job.moveToFailed(new Error("nack: dlq"), job.token ?? "", false);
		}
		this.inflight.delete(args.receipt);
	}

	async close(): Promise<void> {
		for (const queue of this.queues.values()) {
			await queue.close();
		}
		await this.connection.quit();
	}
}
