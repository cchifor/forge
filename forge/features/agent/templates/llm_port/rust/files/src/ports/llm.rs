//! LLM provider port — capability contract for streaming chat completions.
//!
//! Adapters live under `src/adapters/llm_*.rs`. The rest of the app
//! depends on `dyn LlmPort` (or a generic), not the adapter struct —
//! wire one adapter at startup (matching `LLM_PROVIDER`), inject the
//! trait object everywhere else.
//!
//! Cross-language contract: this trait mirrors the TypeSpec
//! `interface LLM` at `forge/templates/_shared/ports/llm/contract.tsp`
//! and is the Rust sibling of the Python `LlmProviderPort` Protocol
//! and the Node `LlmPort` interface. Field names + types match the
//! TypeSpec contract; Rust uses snake_case (`tool_calls`,
//! `finish_reason`) by language convention, with serde renaming at
//! the wire boundary where camelCase is required.
//!
//! Streaming semantics: `complete()` returns a `BoxStream<LlmChunk>`.
//! Implementations MUST emit chunks as they arrive (no internal full-
//! reply buffering). The terminal chunk carries `finish_reason`.

use async_trait::async_trait;
use futures::stream::BoxStream;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

/// Role of a chat message — system, user, assistant, or tool.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ChatRole {
    System,
    User,
    Assistant,
    Tool,
}

/// Tool declaration passed to the model. Mirrors the OpenAI/Anthropic shape.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tool {
    /// Tool name — MUST be unique within a single `complete` call.
    pub name: String,
    /// Human-readable description shown to the model.
    pub description: String,
    /// JSON Schema 2020-12 document describing the tool's argument shape.
    #[serde(rename = "inputSchema")]
    pub input_schema: Value,
}

/// One message in a chat conversation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatMessage {
    /// Speaker role for this message.
    pub role: ChatRole,
    /// Text body — MAY be empty for assistant turns that only emit tool calls.
    pub content: String,
    /// Tool invocations emitted by the assistant on this turn.
    #[serde(default, skip_serializing_if = "Vec::is_empty", rename = "toolCalls")]
    pub tool_calls: Vec<Value>,
    /// Identifies which tool produced this message — required when `role` is `tool`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// Correlation id linking this `tool` message to a prior assistant tool call.
    #[serde(default, skip_serializing_if = "Option::is_none", rename = "toolCallId")]
    pub tool_call_id: Option<String>,
}

/// Prompt envelope passed to `complete` — the message history plus optional tools.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatPrompt {
    /// Chronologically ordered conversation history.
    pub messages: Vec<ChatMessage>,
    /// Tools the model is allowed to invoke this turn.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tools: Vec<Tool>,
}

/// Tuning knobs for one `complete` call.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmOptions {
    /// Provider-specific model identifier (e.g. `gpt-4o`).
    #[serde(rename = "modelId")]
    pub model_id: String,
    /// Sampling temperature — range is provider-specific, typically 0.0-2.0.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub temperature: Option<f32>,
    /// Hard cap on generated tokens; omitted means "use the provider default".
    #[serde(default, skip_serializing_if = "Option::is_none", rename = "maxTokens")]
    pub max_tokens: Option<u32>,
}

/// Streaming delta for an in-progress tool call.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ToolCallChunk {
    /// Tool name being invoked — present on the first chunk of a call.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// Partial JSON arguments accumulated so far.
    #[serde(default, skip_serializing_if = "Option::is_none", rename = "argumentsDelta")]
    pub arguments_delta: Option<String>,
    /// Caller-side correlation id for matching tool calls to results.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
}

/// One chunk from a streaming chat completion.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct LlmChunk {
    /// Text delta appended to the assistant's reply on this chunk.
    pub delta: String,
    /// Set on the terminal chunk — `stop` / `length` / `tool_use` / `content_filter`.
    #[serde(default, skip_serializing_if = "Option::is_none", rename = "finishReason")]
    pub finish_reason: Option<String>,
    /// Tool-call delta, when this chunk advances an in-flight tool invocation.
    #[serde(default, skip_serializing_if = "Option::is_none", rename = "toolCall")]
    pub tool_call: Option<ToolCallChunk>,
}

/// Error variants surfaced by [`LlmPort`] operations.
#[derive(Debug, Error)]
pub enum LlmError {
    /// Underlying transport failure (HTTP error, connection reset, etc).
    #[error("llm transport error: {0}")]
    Transport(String),
    /// Provider rejected the request (auth, quota, invalid model, …).
    #[error("llm provider error: {0}")]
    Provider(String),
    /// Response could not be decoded into the cross-language chunk shape.
    #[error("llm serialization error: {0}")]
    Serialization(String),
}

/// The LLM port. Concrete adapters implement this trait; the rest of
/// the app depends on `dyn LlmPort` (or a generic), not the adapter
/// struct.
///
/// Streaming-only by design (RFC-005 + Pillar D.2): non-streaming is
/// a language-local convenience built on top of `complete` — callers
/// collect chunks into a single message at the call site.
#[async_trait]
pub trait LlmPort: Send + Sync {
    /// Streaming chat completion. Implementations MUST emit chunks as
    /// they arrive — no internal full-reply buffering.
    async fn complete<'a>(
        &'a self,
        prompt: ChatPrompt,
        options: LlmOptions,
    ) -> Result<BoxStream<'a, Result<LlmChunk, LlmError>>, LlmError>;

    /// Batch-embed the given texts. Returns one vector per input, in
    /// the same order as the input slice.
    ///
    /// Default impl returns [`LlmError::Provider`] — providers without
    /// embeddings (or that the project doesn't need) MAY leave this
    /// unimplemented. Callers depending on embeddings should pick a
    /// provider that ships them.
    async fn embed(&self, _texts: Vec<String>) -> Result<Vec<Vec<f32>>, LlmError> {
        Err(LlmError::Provider(
            "embed() not implemented for this adapter".to_string(),
        ))
    }
}
