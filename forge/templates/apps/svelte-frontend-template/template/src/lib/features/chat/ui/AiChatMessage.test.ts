import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from '@testing-library/svelte';
import { tick } from 'svelte';

// Spy on marked.parse so we can count parse-to-HTML calls under streaming.
const { parseSpy } = vi.hoisted(() => ({
	parseSpy: vi.fn((text: string) => `<p>${text}</p>`)
}));

vi.mock('marked', () => ({
	marked: {
		parse: (text: string) => parseSpy(text)
	}
}));

vi.mock('dompurify', () => ({
	default: { sanitize: (html: string) => html }
}));

import AiChatMessage from './AiChatMessage.svelte';

function makeMessage(role: 'user' | 'assistant' | 'system', content: string, id = 'msg-1') {
	return { id, role, content };
}

beforeEach(() => {
	parseSpy.mockClear();
});

describe('AiChatMessage — streaming debounce', () => {
	afterEach(() => {
		vi.useRealTimers();
	});

	it('collapses 10 rapid token updates within 50ms into <= 2 markdown parses', async () => {
		vi.useFakeTimers();
		const { rerender } = render(AiChatMessage, {
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			props: { message: makeMessage('assistant', 'a'), isStreaming: true } as any
		});
		// Initial mount calls renderMarkdown once for the cached HTML.
		const initialCalls = parseSpy.mock.calls.length;

		// 10 token deltas at 5ms intervals — all within the 50ms debounce window.
		for (let i = 0; i < 10; i++) {
			await rerender({
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				message: makeMessage('assistant', 'a' + 'b'.repeat(i + 1)),
				isStreaming: true
			} as any);
			vi.advanceTimersByTime(5);
		}

		// Close the debounce window — at most one debounced render fires.
		vi.advanceTimersByTime(50);
		await tick();

		const renderCalls = parseSpy.mock.calls.length - initialCalls;
		expect(renderCalls).toBeLessThanOrEqual(2);
	});

	it('flushes immediately when isStreaming transitions to false', async () => {
		vi.useFakeTimers();
		const { rerender, container } = render(AiChatMessage, {
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			props: { message: makeMessage('assistant', 'partial'), isStreaming: true } as any
		});
		const baseline = parseSpy.mock.calls.length;

		// New token arrives but the debounce window has not yet elapsed.
		await rerender({
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			message: makeMessage('assistant', 'partial + final'),
			isStreaming: true
		} as any);

		// Stream ends — must render the final content within frame, not after 50ms.
		await rerender({
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			message: makeMessage('assistant', 'partial + final'),
			isStreaming: false
		} as any);
		await tick();

		expect(parseSpy.mock.calls.length).toBeGreaterThan(baseline);
		expect(container.innerHTML).toContain('partial + final');
	});
});
