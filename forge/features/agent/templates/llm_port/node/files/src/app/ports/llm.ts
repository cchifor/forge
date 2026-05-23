/**
 * LLM provider port — capability contract for streaming chat completions.
 *
 * Adapters live under `app/adapters/llm/<provider>.ts`. The rest of the
 * app depends on the `LlmPort` interface, not the concrete adapter
 * class — wire one adapter at startup (matching `LLM_PROVIDER`), inject
 * the typed port everywhere else.
 *
 * Cross-language contract: this interface mirrors the TypeSpec
 * `interface LLM` at `forge/templates/_shared/ports/llm/contract.tsp`
 * and the Python `LlmProviderPort` Protocol at
 * `forge/features/agent/templates/llm_port/python/files/src/app/ports/llm.py`.
 * Field names + types match the TypeSpec contract verbatim; the Python
 * Protocol uses snake_case (`tool_calls`, `tool_call_id`) and is
 * normalised by `LlmMessage` adapters at the boundary.
 *
 * Streaming semantics: `complete()` returns an `AsyncIterable<LlmChunk>`.
 * Implementations MUST emit chunks as they arrive (no internal
 * buffering of the full reply). The terminal chunk carries
 * `finishReason`; intermediate chunks may carry `delta` text and/or
 * a `toolCall` delta.
 */

/** Role of a chat message — system, user, assistant, or tool. */
export type ChatRole = "system" | "user" | "assistant" | "tool";

/** Tool declaration passed to the model. Mirrors the OpenAI/Anthropic shape. */
export interface Tool {
	/** Tool name — MUST be unique within a single `complete` call. */
	name: string;
	/** Human-readable description shown to the model. */
	description: string;
	/** JSON Schema 2020-12 document describing the tool's argument shape. */
	inputSchema: Record<string, unknown>;
}

/** One message in a chat conversation. */
export interface ChatMessage {
	/** Speaker role for this message. */
	role: ChatRole;
	/** Text body — MAY be empty for assistant turns that only emit tool calls. */
	content: string;
	/** Tool invocations emitted by the assistant on this turn. */
	toolCalls?: Array<Record<string, unknown>>;
	/** Identifies which tool produced this message — required when `role` is `tool`. */
	name?: string;
	/** Correlation id linking this `tool` message to a prior assistant tool call. */
	toolCallId?: string;
}

/** Prompt envelope passed to `complete` — the message history plus optional tools. */
export interface ChatPrompt {
	/** Chronologically ordered conversation history. */
	messages: ChatMessage[];
	/** Tools the model is allowed to invoke this turn. */
	tools?: Tool[];
}

/** Tuning knobs for one `complete` call. */
export interface LlmOptions {
	/** Provider-specific model identifier (e.g. `gpt-4o`). */
	modelId: string;
	/** Sampling temperature — range is provider-specific, typically 0.0-2.0. */
	temperature?: number;
	/** Hard cap on generated tokens; omitted means "use the provider default". */
	maxTokens?: number;
}

/** Streaming delta for an in-progress tool call. */
export interface ToolCallChunk {
	/** Tool name being invoked — present on the first chunk of a call. */
	name?: string;
	/** Partial JSON arguments accumulated so far. */
	argumentsDelta?: string;
	/** Caller-side correlation id for matching tool calls to results. */
	id?: string;
}

/** One chunk from a streaming chat completion. */
export interface LlmChunk {
	/** Text delta appended to the assistant's reply on this chunk. */
	delta: string;
	/** Set on the terminal chunk — `stop` / `length` / `tool_use` / `content_filter`. */
	finishReason?: string;
	/** Tool-call delta, when this chunk advances an in-flight tool invocation. */
	toolCall?: ToolCallChunk;
}

/**
 * The LLM port. Concrete adapters implement this interface; the rest
 * of the app depends on the port type, not the adapter class.
 *
 * Streaming-only by design (RFC-005 + Pillar D.2): non-streaming is
 * a language-local convenience built on top of `complete` — callers
 * collect chunks into a single message at the call site.
 */
export interface LlmPort {
	/**
	 * Streaming chat completion. Implementations MUST emit chunks as
	 * they arrive — no internal full-reply buffering.
	 */
	complete(prompt: ChatPrompt, options: LlmOptions): AsyncIterable<LlmChunk>;

	/**
	 * Batch-embed the given texts. Returns one vector per input, in
	 * the same order as the input array.
	 *
	 * Optional in 1.x — adapters whose provider doesn't offer
	 * embeddings (or whose embedding API the project doesn't need)
	 * MAY omit it. Callers that depend on embeddings should pick a
	 * provider that ships them.
	 */
	embed?(texts: string[]): Promise<number[][]>;
}
