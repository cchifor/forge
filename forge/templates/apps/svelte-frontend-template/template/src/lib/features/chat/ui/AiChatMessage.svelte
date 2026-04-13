<script lang="ts">
	import { Bot, User } from 'lucide-svelte';
	import type { ChatMessage } from '$lib/features/chat';
	import { cn } from '$lib/shared/lib/utils';

	let { message }: { message: ChatMessage } = $props();

	const isAssistant = $derived(message.role === 'assistant');
	const timeStr = $derived(
		message.timestamp.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
	);
</script>

<div class={cn('flex gap-3', isAssistant ? '' : 'flex-row-reverse')}>
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
			'max-w-[85%] rounded-lg px-3 py-2 text-sm leading-[1.6]',
			isAssistant
				? 'bg-ai-surface text-ai-surface-foreground border border-ai-border'
				: 'bg-primary text-primary-foreground'
		)}
	>
		<p class="whitespace-pre-wrap break-words">{message.content}</p>
		<span
			class={cn(
				'mt-1 block text-[10px]',
				isAssistant ? 'text-muted-foreground' : 'text-primary-foreground/70'
			)}
		>
			{timeStr}
		</span>
	</div>
</div>
