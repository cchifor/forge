/**
 * Queue port — capability contract for outbound work enqueuing + consumption.
 *
 * Adapters live under `app/adapters/queue/<provider>.ts`. The port's
 * surface covers the 80% case: submit a task, consume a batch, ack on
 * success, nack + retry on failure. Advanced patterns (priority queues,
 * delayed delivery) are provider-specific and stay inside adapters.
 *
 * Mirror of the Python ``app.ports.queue.QueuePort`` Protocol — see
 * docs/rfcs/RFC-012-forgequeue-port.md for the cross-language spec.
 */

/** One message as delivered by a consumer. */
export interface QueueMessage {
	/** Provider-assigned message id. */
	id: string;
	/** Decoded JSON envelope payload. */
	body: Record<string, unknown>;
	/** Opaque handle for ack/nack — provider-specific. */
	receipt: string;
}

export interface EnqueueArgs {
	topic: string;
	body: Record<string, unknown>;
	/** Defaults to 0 — immediate delivery. */
	delaySeconds?: number;
}

export interface ConsumeArgs {
	topic: string;
	/** Defaults to 1. */
	batchSize?: number;
}

export interface AckArgs {
	topic: string;
	receipt: string;
}

export interface NackArgs {
	topic: string;
	receipt: string;
	/** Defaults to true — requeue for retry. ``false`` routes to DLQ. */
	requeue?: boolean;
}

/**
 * The queue port. Concrete adapters implement this interface; the rest
 * of the app depends on the port type, not the adapter class.
 */
export interface QueuePort {
	/** Enqueue one message; resolve to the provider's message id. */
	enqueue(args: EnqueueArgs): Promise<string>;

	/**
	 * Yield messages from the named topic. The consumer is responsible
	 * for calling ``ack`` (success) or ``nack`` (retry / DLQ) for each
	 * yielded message.
	 */
	consume(args: ConsumeArgs): AsyncIterable<QueueMessage>;

	/** Acknowledge a message — removes it from the queue. */
	ack(args: AckArgs): Promise<void>;

	/** Reject a message — requeue by default for retry. */
	nack(args: NackArgs): Promise<void>;
}
