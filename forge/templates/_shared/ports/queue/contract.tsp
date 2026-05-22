// queue_port — TypeSpec contract for the durable-async-work port.
//
// Source of truth: RFC-005 § "Port Contracts" → queue_port.
// The bodies below match the RFC verbatim; if you change one, change
// the other and call it out in the PR.
//
// Spec-only. No code is generated from this file today. The Python
// reference adapter lives at
// `forge/features/async_work/templates/queue_port/python/files/src/app/ports/queue.py`;
// the Python surface differs in two RFC-blessed ways:
//
//   * Python `consume(topic, batch_size)` returns `AsyncIterator[QueueMessage]`;
//     the RFC's `poll(topic, maxMessages)` is the language-neutral spelling
//     (returning a finite batch lets Rust/Node implementations stay sync at
//     the port boundary; consumers loop on `poll`).
//   * Python `nack(receipt, requeue=True)` uses an opaque receipt handle;
//     the RFC uses the job id directly. Adapters MAY map receipt→id
//     internally, but the cross-language wire shape is `jobId: string`.
//
// See RFC-012 for the Python-side rationale on the receipt-vs-id split.

import "@typespec/openapi3";

@service(#{ title: "Queue Port" })
namespace ForgeQueue;

@doc("Options that influence how a job is scheduled.")
model EnqueueOptions {
  @doc("Delay before the message becomes visible to consumers.")
  delaySeconds?: int32;
  @doc("Opaque per-message deduplication key. Adapters that lack native dedup MAY ignore this.")
  dedupKey?: string;
}

@doc("A durable async job as delivered by `poll`.")
model Job {
  @doc("Provider-assigned unique id; opaque to callers.")
  id: string;
  @doc("Topic the job was enqueued on.")
  topic: string;
  @doc("Opaque payload bytes; encoding is the caller's responsibility.")
  body: bytes;
  @doc("Number of prior delivery attempts (0 on first delivery).")
  attempts: int32;
  @doc("UTC timestamp the job is scheduled to run; absent for ready-now jobs.")
  scheduledFor?: utcDateTime;
}

@doc("Cross-language queue capability — enqueue, poll, ack, nack.")
interface Queue {
  @doc("Enqueue one message; returns the provider's job id.")
  enqueue(topic: string, body: bytes, options?: EnqueueOptions): string;

  @doc("Pull up to `maxMessages` jobs from `topic`. MAY return fewer; MAY return zero.")
  poll(topic: string, maxMessages: int32): Job[];

  @doc("Acknowledge a successfully processed job; removes it from the queue.")
  ack(jobId: string): void;

  @doc("Reject a job; if `requeue` is true (default), the job becomes redeliverable.")
  nack(jobId: string, requeue?: boolean): void;
}
