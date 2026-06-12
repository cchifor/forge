//! Queue port — capability contract for outbound work enqueuing + consumption.
//!
//! Adapters live under `src/adapters/queue_*.rs`. The port's surface
//! covers the 80% case: submit a task, consume a batch, ack on success,
//! nack + retry on failure. Advanced patterns (priority queues, delayed
//! delivery) are provider-specific and stay inside adapters.
//!
//! Mirror of the Python `app.ports.queue.QueuePort` Protocol and the
//! Node `QueuePort` interface — see docs/rfcs/RFC-012-forgequeue-port.md
//! for the cross-language spec.

use async_trait::async_trait;
use futures::stream::BoxStream;
use serde_json::Value;
use thiserror::Error;

/// One message as delivered by a consumer.
#[derive(Debug, Clone)]
pub struct QueueMessage {
    /// Provider-assigned message id.
    pub id: String,
    /// Decoded JSON envelope payload.
    pub body: Value,
    /// Opaque handle for ack/nack — provider-specific.
    pub receipt: String,
}

/// Error variants surfaced by `QueuePort` operations.
#[derive(Debug, Error)]
pub enum QueueError {
    /// Underlying transport failure (Redis disconnect, AWS API error, etc).
    #[error("queue transport error: {0}")]
    Transport(String),
    /// Message body could not be encoded / decoded as JSON.
    #[error("queue serialization error: {0}")]
    Serialization(String),
    /// `ack` / `nack` called with a receipt the adapter doesn't recognise.
    #[error("queue receipt not in flight: {0}")]
    UnknownReceipt(String),
}

/// The queue port. Concrete adapters implement this trait; the rest of
/// the app depends on `dyn QueuePort` (or a generic), not the adapter
/// struct.
#[async_trait]
pub trait QueuePort: Send + Sync {
    /// Enqueue one message; return the provider's message id.
    ///
    /// `delay_seconds == 0` is immediate delivery.
    async fn enqueue(
        &self,
        topic: &str,
        body: Value,
        delay_seconds: u64,
    ) -> Result<String, QueueError>;

    /// Open a consumer stream on `topic`. Each yielded `QueueMessage`
    /// must be ack-ed or nack-ed via the same adapter.
    fn consume<'a>(
        &'a self,
        topic: &'a str,
        batch_size: usize,
    ) -> BoxStream<'a, Result<QueueMessage, QueueError>>;

    /// Acknowledge a message — removes it from the queue.
    async fn ack(&self, topic: &str, receipt: &str) -> Result<(), QueueError>;

    /// Reject a message — requeue (default) or send to DLQ if
    /// `requeue == false`.
    async fn nack(&self, topic: &str, receipt: &str, requeue: bool) -> Result<(), QueueError>;
}
