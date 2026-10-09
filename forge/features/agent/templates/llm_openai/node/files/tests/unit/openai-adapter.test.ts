import { beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => ({
	streamText: vi.fn(),
	chat: vi.fn(() => "chat-model"),
}));
vi.mock("@ai-sdk/openai", () => ({ createOpenAI: () => ({ chat: sdk.chat }) }));
vi.mock("ai", () => ({
	streamText: sdk.streamText,
	embed: vi.fn(),
	jsonSchema: (value: unknown) => value,
}));
import { OpenAiAdapter } from "../../src/app/adapters/llm/openai.js";

async function* events(values: unknown[]) {
	yield* values;
}

describe("OpenAI streaming adapter", () => {
	beforeEach(() => vi.clearAllMocks());

	it("preserves chat requests and reconstructs parallel tool inputs exactly once", async () => {
		sdk.streamText.mockReturnValue({
			fullStream: events([
				{ type: "text-delta", text: "Checking" },
				{ type: "tool-input-start", id: "a", toolName: "search" },
				{ type: "tool-input-start", id: "b", toolName: "fetch" },
				{ type: "tool-input-delta", id: "a", delta: '{"q":' },
				{ type: "tool-input-delta", id: "b", delta: '{"id":2}' },
				{ type: "tool-input-delta", id: "a", delta: '"test"}' },
				{
					type: "tool-call",
					toolCallId: "a",
					toolName: "search",
					input: { q: "test" },
				},
				{
					type: "tool-call",
					toolCallId: "b",
					toolName: "fetch",
					input: { id: 2 },
				},
				{ type: "finish", finishReason: "tool-calls" },
			]),
		});
		const chunks = await Array.fromAsync(
			new OpenAiAdapter("test-key").complete(
				{ messages: [{ role: "user", content: "Look it up" }], tools: [] },
				{ modelId: "test-model", maxTokens: 100 },
			),
		);
		expect(sdk.chat).toHaveBeenCalledWith("test-model");
		expect(sdk.streamText).toHaveBeenCalledWith(
			expect.objectContaining({ maxOutputTokens: 100 }),
		);
		expect(chunks[0]).toEqual({ delta: "Checking" });
		for (const [id, expected] of [
			["a", '{"q":"test"}'],
			["b", '{"id":2}'],
		]) {
			expect(
				chunks
					.filter((c) => c.toolCall?.id === id)
					.map((c) => c.toolCall?.argumentsDelta ?? "")
					.join(""),
			).toBe(expected);
		}
		expect(chunks.at(-1)?.finishReason).toBe("tool-calls");
	});

	it("accepts a complete tool call when the provider omits input deltas", async () => {
		sdk.streamText.mockReturnValue({
			fullStream: events([
				{
					type: "tool-call",
					toolCallId: "c",
					toolName: "lookup",
					input: { id: 1 },
				},
				{ type: "error", error: new Error("provider failed") },
			]),
		});
		const chunks = await Array.fromAsync(
			new OpenAiAdapter("test-key").complete(
				{ messages: [], tools: [] },
				{ modelId: "test-model" },
			),
		);
		expect(chunks[0]?.toolCall).toEqual({
			id: "c",
			name: "lookup",
			argumentsDelta: '{"id":1}',
		});
		expect(chunks.at(-1)?.finishReason).toBe("error");
	});

	it.each([false, true])(
		"preserves buffered arguments after an input start (empty delta: %s)",
		async (emptyDelta) => {
			sdk.streamText.mockReturnValue({
				fullStream: events([
					{ type: "tool-input-start", id: "d", toolName: "lookup" },
					...(emptyDelta
						? [{ type: "tool-input-delta", id: "d", delta: "" }]
						: []),
					{
						type: "tool-call",
						toolCallId: "d",
						toolName: "lookup",
						input: { id: 4 },
					},
					{ type: "finish", finishReason: "tool-calls" },
				]),
			});
			const chunks = await Array.fromAsync(
				new OpenAiAdapter("test-key").complete(
					{ messages: [], tools: [] },
					{ modelId: "test-model" },
				),
			);
			expect(
				chunks
					.filter((c) => c.toolCall?.id === "d")
					.map((c) => c.toolCall?.argumentsDelta ?? "")
					.join(""),
			).toBe('{"id":4}');
			expect(chunks.at(-1)?.finishReason).toBe("tool-calls");
		},
	);
});
