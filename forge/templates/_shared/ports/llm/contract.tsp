// llm_port — TypeSpec contract for the LLM-provider port.
//
// Source of truth: RFC-005 § "Port Contracts" → llm_port.
// The `LlmChunk` model + `interface LLM` block follow the RFC. Supporting
// types (ChatPrompt, ChatMessage, ToolCallChunk, LlmOptions, Tool) are
// introduced here because the RFC's TypeSpec block referenced them by name
// without defining the bodies — the shapes mirror the Python reference at
// `forge/features/agent/templates/llm_port/python/files/src/app/ports/llm.py`
// (LlmMessage / LlmTool / LlmStreamChunk).
//
// Spec-only. No code is generated from this file today.
//
// Reconciliation notes:
//   * The RFC's `complete(prompt, options) -> LlmChunk[]` is the streaming
//     contract — implementations MUST emit chunks as they arrive. The
//     Python reference splits this into `complete_stream` (the streaming
//     primitive) and `complete` (a non-streaming convenience). The
//     cross-language contract is streaming-only; non-streaming is a
//     language-local convenience built on top of `complete`.
//   * The RFC's `embed(texts) -> float32[][]` matches the embeddings
//     pattern used by every Python adapter under
//     `forge/features/agent/templates/llm_*/python/...`.
//   * Streaming semantics (Python `AsyncIterator`, Node `AsyncIterable`,
//     Rust `futures::Stream`) are the language-binding concern; the
//     contract is the chunk shape and the ordering guarantee.

import "@typespec/openapi3";

@service(#{ title: "LLM Port" })
namespace ForgeLlm;

@doc("Role of a chat message — system, user, assistant, or tool.")
enum ChatRole {
  system,
  user,
  assistant,
  tool,
}

@doc("Tool declaration passed to the model; mirrors the OpenAI/Anthropic shape.")
model Tool {
  @doc("Tool name; MUST be unique within a single `complete` call.")
  name: string;
  @doc("Human-readable description shown to the model.")
  description: string;
  @doc("JSON Schema 2020-12 document describing the tool's argument shape.")
  inputSchema: Record<unknown>;
}

@doc("One message in a chat conversation.")
model ChatMessage {
  @doc("Speaker role for this message.")
  role: ChatRole;
  @doc("Text body. MAY be empty for assistant turns that only emit tool calls.")
  content: string;
  @doc("Tool invocations emitted by the assistant on this turn.")
  toolCalls?: Record<unknown>[];
  @doc("Identifies which tool produced this message; required when `role` is `tool`.")
  name?: string;
  @doc("Correlation id linking this `tool` message to a prior assistant tool call.")
  toolCallId?: string;
}

@doc("Prompt envelope passed to `complete` — the message history plus optional tools.")
model ChatPrompt {
  @doc("Chronologically ordered conversation history.")
  messages: ChatMessage[];
  @doc("Tools the model is allowed to invoke this turn.")
  tools?: Tool[];
}

@doc("Tuning knobs for one `complete` call.")
model LlmOptions {
  @doc("Provider-specific model identifier (e.g. `gpt-4o`, `claude-opus-4-7`).")
  modelId: string;
  @doc("Sampling temperature; range is provider-specific, typically 0.0–2.0.")
  temperature?: float32;
  @doc("Hard cap on generated tokens; absent means use the provider default.")
  maxTokens?: int32;
}

@doc("Streaming delta for an in-progress tool call.")
model ToolCallChunk {
  @doc("Tool name being invoked; present on the first chunk of a call.")
  name?: string;
  @doc("Partial JSON arguments accumulated so far.")
  argumentsDelta?: string;
  @doc("Caller-side correlation id for matching tool calls to results.")
  id?: string;
}

@doc("One chunk from a streaming chat completion.")
model LlmChunk {
  @doc("Text delta appended to the assistant's reply on this chunk.")
  delta: string;
  @doc("Set on the terminal chunk; one of `stop`, `length`, `tool_use`, `content_filter`.")
  finishReason?: string;
  @doc("Tool-call delta, when this chunk advances an in-flight tool invocation.")
  toolCall?: ToolCallChunk;
}

@doc("Cross-language LLM capability — streaming completion + embeddings.")
interface LLM {
  @doc("""
    Streaming chat completion. Implementations MUST emit chunks as they arrive
    — the return type is an async stream in every target language, not a
    pre-materialised array. TypeSpec lacks a first-class `AsyncIterable<T>`
    primitive at the time of this contract, so the IR-level shape is
    `LlmChunk[]` as a stand-in; language bindings translate to their
    native stream type:
      - TypeScript: `AsyncIterable<LlmChunk>` (Node)
      - Rust:       `BoxStream<'a, Result<LlmChunk, LlmError>>`
      - Python:     `AsyncIterator[LlmChunk]`
    Multi-tool fan-out: one provider chunk MAY produce multiple
    `LlmChunk` records (one per simultaneous tool-call) — the
    consumer reconstructs parallel-tool boundaries from `toolCall.id`.
  """)
  complete(prompt: ChatPrompt, options: LlmOptions): LlmChunk[];

  @doc("Batch-embed the given texts. Returns one vector per input, in order.")
  embed(texts: string[]): float32[][];
}
