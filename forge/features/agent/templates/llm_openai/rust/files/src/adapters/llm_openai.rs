//! OpenAI adapter for [`LlmPort`] — backed by the `async-openai` crate.
//!
//! Delivery: streaming. `complete()` returns a `BoxStream<LlmChunk>`
//! built from `async-openai`'s `chat().create_stream(...)` response;
//! each provider chunk is translated to the port's [`LlmChunk`] shape
//! so callers don't leak provider-specific event types.
//!
//! The chosen adapter wires itself behind the `LlmPort` trait at
//! startup (see `inject.yaml`); the rest of the app holds a
//! `dyn LlmPort` (or generic) and never touches `async-openai`
//! directly.

use async_openai::{
    config::OpenAIConfig,
    types::{
        ChatCompletionRequestAssistantMessageArgs, ChatCompletionRequestMessage,
        ChatCompletionRequestSystemMessageArgs, ChatCompletionRequestToolMessageArgs,
        ChatCompletionRequestUserMessageArgs, ChatCompletionToolArgs, ChatCompletionToolType,
        CreateChatCompletionRequestArgs, CreateEmbeddingRequestArgs, FunctionObjectArgs,
    },
    Client,
};
use async_trait::async_trait;
use futures::stream::{BoxStream, StreamExt};

use crate::ports::llm::{
    ChatMessage, ChatPrompt, ChatRole, LlmChunk, LlmError, LlmOptions, LlmPort, Tool,
    ToolCallChunk,
};

const DEFAULT_EMBED_MODEL: &str = "text-embedding-3-small";

fn api_key() -> String {
    std::env::var("OPENAI_API_KEY").unwrap_or_default()
}

fn base_url() -> Option<String> {
    std::env::var("OPENAI_BASE_URL").ok().filter(|s| !s.is_empty())
}

/// OpenAI adapter. Owns a single `async_openai::Client` re-used across
/// requests — the client wraps `reqwest::Client` which is `Clone`-able
/// and connection-pooled, so one adapter instance per process is the
/// right shape for the port contract.
pub struct OpenAiAdapter {
    client: Client<OpenAIConfig>,
}

impl OpenAiAdapter {
    pub fn new() -> Self {
        let mut cfg = OpenAIConfig::new().with_api_key(api_key());
        if let Some(url) = base_url() {
            cfg = cfg.with_api_base(url);
        }
        Self {
            client: Client::with_config(cfg),
        }
    }

    pub fn with_config(cfg: OpenAIConfig) -> Self {
        Self {
            client: Client::with_config(cfg),
        }
    }
}

impl Default for OpenAiAdapter {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl LlmPort for OpenAiAdapter {
    async fn complete<'a>(
        &'a self,
        prompt: ChatPrompt,
        options: LlmOptions,
    ) -> Result<BoxStream<'a, Result<LlmChunk, LlmError>>, LlmError> {
        let messages: Result<Vec<ChatCompletionRequestMessage>, LlmError> =
            prompt.messages.into_iter().map(to_openai_message).collect();
        let messages = messages?;

        let mut req_builder = CreateChatCompletionRequestArgs::default();
        req_builder.model(&options.model_id).messages(messages);
        if let Some(t) = options.temperature {
            req_builder.temperature(t);
        }
        if let Some(m) = options.max_tokens {
            req_builder.max_tokens(m);
        }
        if !prompt.tools.is_empty() {
            let tools: Result<Vec<_>, LlmError> =
                prompt.tools.into_iter().map(to_openai_tool).collect();
            req_builder.tools(tools?);
        }

        let request = req_builder
            .build()
            .map_err(|e| LlmError::Serialization(e.to_string()))?;

        let stream = self
            .client
            .chat()
            .create_stream(request)
            .await
            .map_err(|e| LlmError::Provider(e.to_string()))?;

        // Translate each OpenAI streaming chunk to the port's
        // [`LlmChunk`] shape. Errors mid-stream surface as
        // [`LlmError::Transport`] so the consumer can decide whether
        // to retry or surface to the caller.
        let mapped = stream.map(|item| match item {
            Ok(resp) => {
                let choice = match resp.choices.into_iter().next() {
                    Some(c) => c,
                    None => {
                        return Ok(LlmChunk {
                            delta: String::new(),
                            finish_reason: None,
                            tool_call: None,
                        });
                    }
                };
                let delta = choice.delta;
                let text = delta.content.unwrap_or_default();
                let finish_reason = choice.finish_reason.map(|fr| {
                    // `FinishReason` is a serde-tagged enum upstream;
                    // serialise back to its on-wire string so the
                    // cross-language contract stays exact.
                    serde_json::to_value(fr)
                        .ok()
                        .and_then(|v| v.as_str().map(String::from))
                        .unwrap_or_else(|| "stop".to_string())
                });
                let tool_call = delta.tool_calls.and_then(|tcs| tcs.into_iter().next()).map(
                    |tc| ToolCallChunk {
                        id: Some(tc.id.clone().unwrap_or_default()),
                        name: tc.function.as_ref().and_then(|f| f.name.clone()),
                        arguments_delta: tc.function.as_ref().and_then(|f| f.arguments.clone()),
                    },
                );
                Ok(LlmChunk {
                    delta: text,
                    finish_reason,
                    tool_call,
                })
            }
            Err(e) => Err(LlmError::Transport(e.to_string())),
        });

        Ok(Box::pin(mapped))
    }

    async fn embed(&self, texts: Vec<String>) -> Result<Vec<Vec<f32>>, LlmError> {
        let request = CreateEmbeddingRequestArgs::default()
            .model(DEFAULT_EMBED_MODEL)
            .input(texts)
            .build()
            .map_err(|e| LlmError::Serialization(e.to_string()))?;
        let resp = self
            .client
            .embeddings()
            .create(request)
            .await
            .map_err(|e| LlmError::Provider(e.to_string()))?;
        Ok(resp.data.into_iter().map(|d| d.embedding).collect())
    }
}

fn to_openai_message(m: ChatMessage) -> Result<ChatCompletionRequestMessage, LlmError> {
    match m.role {
        ChatRole::System => Ok(ChatCompletionRequestSystemMessageArgs::default()
            .content(m.content)
            .build()
            .map_err(|e| LlmError::Serialization(e.to_string()))?
            .into()),
        ChatRole::User => Ok(ChatCompletionRequestUserMessageArgs::default()
            .content(m.content)
            .build()
            .map_err(|e| LlmError::Serialization(e.to_string()))?
            .into()),
        ChatRole::Assistant => Ok(ChatCompletionRequestAssistantMessageArgs::default()
            .content(m.content)
            .build()
            .map_err(|e| LlmError::Serialization(e.to_string()))?
            .into()),
        ChatRole::Tool => Ok(ChatCompletionRequestToolMessageArgs::default()
            .content(m.content)
            .tool_call_id(m.tool_call_id.unwrap_or_default())
            .build()
            .map_err(|e| LlmError::Serialization(e.to_string()))?
            .into()),
    }
}

fn to_openai_tool(t: Tool) -> Result<async_openai::types::ChatCompletionTool, LlmError> {
    ChatCompletionToolArgs::default()
        .r#type(ChatCompletionToolType::Function)
        .function(
            FunctionObjectArgs::default()
                .name(t.name)
                .description(t.description)
                .parameters(t.input_schema)
                .build()
                .map_err(|e| LlmError::Serialization(e.to_string()))?,
        )
        .build()
        .map_err(|e| LlmError::Serialization(e.to_string()))
}
