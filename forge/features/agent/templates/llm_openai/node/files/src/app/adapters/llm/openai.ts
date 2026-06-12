/**
 * OpenAI adapter for `LlmPort`. Wraps the Vercel AI SDK
 * (`ai` + `@ai-sdk/openai`) so the application talks to OpenAI
 * through one provider-neutral surface.
 *
 * Delivery: streaming. `complete()` returns an `AsyncIterable<LlmChunk>`
 * backed by the AI SDK's `streamText` helper — its `fullStream` emits
 * text deltas, tool-call deltas, and finish events, each translated
 * to the port's chunk shape so callers don't leak provider-specific
 * event types.
 *
 * The chosen adapter wires itself behind the `LlmPort` interface at
 * startup (see `inject.yaml`); the rest of the app imports the port
 * type, not this class.
 */

import { createOpenAI } from "@ai-sdk/openai";
import { embed as aiEmbed, jsonSchema, streamText, type CoreMessage, type ToolSet } from "ai";

import type {
	ChatMessage,
	ChatPrompt,
	LlmChunk,
	LlmOptions,
	LlmPort,
	Tool,
} from "../../ports/llm.js";

export class OpenAiAdapter implements LlmPort {
	private readonly provider: ReturnType<typeof createOpenAI>;

	constructor(apiKey?: string, baseURL?: string) {
		const resolvedKey = apiKey ?? process.env.OPENAI_API_KEY ?? "";
		const resolvedBaseUrl = baseURL ?? process.env.OPENAI_BASE_URL ?? undefined;
		this.provider = createOpenAI({
			apiKey: resolvedKey,
			...(resolvedBaseUrl ? { baseURL: resolvedBaseUrl } : {}),
		});
	}

	complete(prompt: ChatPrompt, options: LlmOptions): AsyncIterable<LlmChunk> {
		const model = this.provider(options.modelId);
		const messages: CoreMessage[] = prompt.messages.map(toCoreMessage);
		const tools = prompt.tools ? toAiTools(prompt.tools) : undefined;

		const result = streamText({
			model,
			messages,
			temperature: options.temperature,
			maxTokens: options.maxTokens,
			...(tools ? { tools } : {}),
			// Codex Phase B round 1 follow-up: AI SDK 4 gates
			// tool-call delta streaming behind `toolCallStreaming: true`.
			// Without this, tool-call ARGUMENTS arrive as one final
			// `tool-call` event with no incremental delta, defeating
			// the port's `arguments_delta` field semantic. Enable
			// unconditionally — the cost when no tools are configured
			// is zero (no tool-call events fire either way).
			toolCallStreaming: true,
		});

		return mapStream(result.fullStream);
	}

	async embed(texts: string[]): Promise<number[][]> {
		// AI SDK's `embed` takes one value at a time; the cross-language
		// port commits to batch semantics, so loop. Adapters with a
		// native batch endpoint (`openai.embeddings.create` accepts an
		// array) can swap this for one round-trip per batch.
		const model = this.provider.textEmbeddingModel("text-embedding-3-small");
		const out: number[][] = [];
		for (const value of texts) {
			const { embedding } = await aiEmbed({ model, value });
			out.push(embedding);
		}
		return out;
	}
}

function toCoreMessage(m: ChatMessage): CoreMessage {
	// AI SDK's `CoreMessage` shape is role-discriminated; assistant
	// turns with tool calls use a parts array, plain text messages use
	// a string. This mapping handles the common cases — provider-
	// specific edge cases (e.g. mixed text+tool turns) live in the
	// adapter, not the port.
	switch (m.role) {
		case "system":
			return { role: "system", content: m.content };
		case "user":
			return { role: "user", content: m.content };
		case "assistant":
			return { role: "assistant", content: m.content };
		case "tool":
			return {
				role: "tool",
				content: [
					{
						type: "tool-result",
						toolCallId: m.toolCallId ?? "",
						toolName: m.name ?? "",
						result: m.content,
					},
				],
			};
		default: {
			const _exhaustive: never = m.role;
			return { role: "user", content: m.content, _unreachable: _exhaustive } as never;
		}
	}
}

function toAiTools(tools: Tool[]): ToolSet {
	// AI SDK takes tools as a `{ toolName: {description, parameters} }`
	// dictionary; the JSON Schema is wrapped with `jsonSchema()` so each entry
	// is a SDK `Schema` and the dict satisfies `ToolSet` (not a raw object —
	// AI SDK 4 typed `tools` as `ToolSet`). Strict schema-validation lives one
	// level up in the agent loop.
	const out: ToolSet = {};
	for (const tool of tools) {
		out[tool.name] = {
			description: tool.description,
			parameters: jsonSchema(tool.inputSchema as Parameters<typeof jsonSchema>[0]),
		};
	}
	return out;
}

async function* mapStream(
	source: AsyncIterable<unknown>,
): AsyncIterable<LlmChunk> {
	// AI SDK's `fullStream` emits a discriminated union of events. We
	// translate text-delta + tool-call deltas + finish chunks; other
	// event types (step-start, reasoning, source) are no-ops for the
	// cross-language chunk contract.
	for await (const part of source) {
		const evt = part as { type?: string } & Record<string, unknown>;
		switch (evt.type) {
			case "text-delta":
				yield { delta: (evt.textDelta as string) ?? "" };
				break;
			case "tool-call-delta":
				yield {
					delta: "",
					toolCall: {
						id: evt.toolCallId as string | undefined,
						name: evt.toolName as string | undefined,
						argumentsDelta: evt.argsTextDelta as string | undefined,
					},
				};
				break;
			case "tool-call":
				yield {
					delta: "",
					toolCall: {
						id: evt.toolCallId as string | undefined,
						name: evt.toolName as string | undefined,
						argumentsDelta: JSON.stringify(evt.args ?? {}),
					},
				};
				break;
			case "finish":
				yield {
					delta: "",
					finishReason: (evt.finishReason as string | undefined) ?? "stop",
				};
				break;
			case "error":
				// Surface as a terminal chunk; callers can inspect
				// `finishReason === "error"` to branch. The underlying
				// error is logged by the agent loop, not re-thrown
				// mid-stream (re-throw would strand the consumer's
				// `for await` without a finalising chunk).
				yield { delta: "", finishReason: "error" };
				return;
			default:
				// Unknown event kind — ignore. AI SDK adds new event types
				// in minor releases; tolerating them keeps the adapter
				// forward-compatible.
				break;
		}
	}
}
