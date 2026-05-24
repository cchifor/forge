<script lang="ts">
	import DOMPurify from 'dompurify';
	import { marked } from 'marked';
	import { Bot, RefreshCw, User } from 'lucide-svelte';
	import type { Message, ToolCallInfo } from '../chat.types';
	import { cn } from '$lib/shared/lib/utils';
	import ToolCallStatus from './ToolCallStatus.svelte';

	let {
		message,
		toolCalls = [],
		onRegenerate,
		isStreaming = false
	}: {
		message: Message;
		toolCalls?: ToolCallInfo[];
		isStreaming?: boolean;
		/**
		 * Show a Regenerate button on this assistant message. Parent
		 * decides — typically only wired on the last assistant message
		 * when no run is in flight.
		 */
		onRegenerate?: (messageId: string) => void;
	} = $props();

	const isAssistant = $derived(message.role !== 'user');

	// Token-streaming markdown debounce.
	//
	// Why: each TEXT_MESSAGE_CONTENT delta would otherwise re-parse the entire
	// assistant message through marked + DOMPurify and patch a fresh HTML tree
	// into the DOM. Typing-rate tokens (~5-20/sec from typical models) thrash
	// reconciliation. We collapse bursts into a single render every ~50ms and
	// always flush on stream end so the final tokens land within one frame.
	const MARKDOWN_DEBOUNCE_MS = 50;

	function renderMarkdown(text: string): string {
		const html = marked.parse(text || '', { async: false }) as string;
		return DOMPurify.sanitize(html);
	}

	// Raw `message.content` remains the source of truth; we debounce only the
	// parse-to-HTML step. `runed` is not a template dep, so we implement the
	// debounce with a `$state` cell and a `setTimeout` driven by `$effect`.
	let renderedHtml = $state(renderMarkdown(message.content || ''));
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;

	function clearTimer() {
		if (debounceTimer !== null) {
			clearTimeout(debounceTimer);
			debounceTimer = null;
		}
	}

	$effect(() => {
		// Track both reactive deps so Svelte 5's runes re-run on either change.
		const raw = message.content || '';
		const streaming = isStreaming;

		clearTimer();
		if (!streaming) {
			// Non-streaming render (initial mount, edit replay, or stream end):
			// flush synchronously so the final tokens appear within one frame.
			renderedHtml = renderMarkdown(raw);
			return;
		}
		debounceTimer = setTimeout(() => {
			renderedHtml = renderMarkdown(raw);
			debounceTimer = null;
		}, MARKDOWN_DEBOUNCE_MS);

		return clearTimer;
	});
</script>

<div
	class={cn('flex gap-3', isAssistant ? '' : 'flex-row-reverse')}
	data-testid="chat-message"
	data-role={message.role}
	data-message-id={message.id}
>
	{#if isAssistant}
		<div
			class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
			style="background: linear-gradient(135deg, hsl(var(--ai-gradient-from)), hsl(var(--ai-gradient-to)))"
		>
			<Bot class="h-4 w-4 text-white" />
		</div>
	{:else}
		<div
			class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground"
		>
			<User class="h-4 w-4" />
		</div>
	{/if}

	<div
		class={cn(
			'flex max-w-[85%] flex-col gap-2 rounded-lg px-3 py-2 text-sm leading-[1.6]',
			isAssistant
				? 'bg-ai-surface text-ai-surface-foreground border border-ai-border'
				: 'bg-primary text-primary-foreground'
		)}
	>
		<div class="prose prose-sm dark:prose-invert max-w-none break-words">
			{@html renderedHtml}
		</div>
		{#if isAssistant && toolCalls.length > 0}
			<div class="flex flex-wrap gap-1.5">
				{#each toolCalls as tc (tc.id)}
					<ToolCallStatus toolCall={tc} />
				{/each}
			</div>
		{/if}
		{#if isAssistant && onRegenerate}
			<button
				type="button"
				class="mt-1 flex items-center gap-1 self-start text-[10px] text-muted-foreground hover:text-foreground transition-colors"
				aria-label="Regenerate response"
				data-testid="chat-message-regenerate"
				onclick={() => onRegenerate?.(message.id)}
			>
				<RefreshCw class="h-3 w-3" />
				Regenerate
			</button>
		{/if}
	</div>
</div>
