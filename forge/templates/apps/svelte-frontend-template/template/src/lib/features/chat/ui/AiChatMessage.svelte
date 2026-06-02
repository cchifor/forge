<script lang="ts">
	import DOMPurify from 'dompurify';
	import { marked } from 'marked';
	import { Bot, RefreshCw, User } from 'lucide-svelte';
	import type { ToolCallInfo } from '../chat.types';
	import type { ChatMessage as Message } from '@forge/canvas-core';
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
		onRegenerate?: (messageId: string) => void;
		isStreaming?: boolean;
	} = $props();

	const isAssistant = $derived(message.role !== 'user');

	const renderedHtml = $derived.by(() => {
		const raw = message.content || '';
		const html = marked.parse(raw, { async: false }) as string;
		return DOMPurify.sanitize(html);
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
