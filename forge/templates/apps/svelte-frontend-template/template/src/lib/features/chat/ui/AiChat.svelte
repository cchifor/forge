<script lang="ts">
	import { X, MessageCircle } from 'lucide-svelte';
	import { getUiStore } from '$lib/features/shell';
	import { getChatStore } from '$lib/features/chat';
	import AiChatMessage from './AiChatMessage.svelte';
	import AiChatInput from './AiChatInput.svelte';
	import type { ChatMode } from '$lib/features/shell';

	let { mode = 'inline' }: { mode?: ChatMode } = $props();

	const ui = getUiStore();
	const chat = getChatStore();

	let messagesContainer: HTMLDivElement | undefined;
	let chatInputRef: AiChatInput | undefined;

	// Auto-scroll to bottom when new messages arrive
	$effect(() => {
		const _ = chat.messages.length;
		if (messagesContainer) {
			requestAnimationFrame(() => {
				if (messagesContainer) {
					messagesContainer.scrollTop = messagesContainer.scrollHeight;
				}
			});
		}
	});

	// Focus input when chat opens
	$effect(() => {
		if (ui.chatOpen && chatInputRef) {
			setTimeout(() => chatInputRef?.focusInput(), 350);
		}
	});

	function handlePanelKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			ui.closeChat();
		}
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<aside
	id="ai-chat-panel"
	class="flex h-full flex-col bg-background border-ai-border"
	aria-label="AI Chat"
	onkeydown={handlePanelKeydown}
>
	<!-- Header -->
	<div class="flex h-14 shrink-0 items-center justify-between border-b border-ai-border px-4">
		<div class="flex items-center gap-2">
			<MessageCircle class="h-4 w-4 text-ai-accent" />
			<span class="text-sm font-semibold">AI Chat</span>
		</div>
		<div class="flex items-center gap-1">
			<span
				class="rounded-full bg-ai-surface px-2.5 py-0.5 text-xs text-ai-surface-foreground"
			>
				{chat.contextLabel}
			</span>
			<button
				class="btn-press rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
				onclick={() => ui.closeChat()}
				aria-label="Close AI Chat"
			>
				<X class="h-4 w-4" />
			</button>
		</div>
	</div>

	<!-- Messages -->
	<div bind:this={messagesContainer} class="flex-1 overflow-y-auto p-4 space-y-4">
		{#if chat.messages.length === 0}
			<div class="flex h-full flex-col items-center justify-center px-6 text-center">
				<div
					class="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-ai-surface"
				>
					<MessageCircle class="h-6 w-6 text-ai-accent" />
				</div>
				<h3 class="mb-1 text-sm font-medium">How can I help?</h3>
				<p class="text-xs text-muted-foreground">
					Ask a question or describe what you need help with.
				</p>
			</div>
		{:else}
			{#each chat.messages as message (message.id)}
				<AiChatMessage {message} />
			{/each}
			{#if chat.isGenerating}
				<div class="flex items-center gap-2 text-xs text-muted-foreground">
					<div class="flex gap-1">
						<span
							class="h-1.5 w-1.5 rounded-full bg-ai-accent animate-bounce [animation-delay:0ms]"
						></span>
						<span
							class="h-1.5 w-1.5 rounded-full bg-ai-accent animate-bounce [animation-delay:150ms]"
						></span>
						<span
							class="h-1.5 w-1.5 rounded-full bg-ai-accent animate-bounce [animation-delay:300ms]"
						></span>
					</div>
					<span>Thinking...</span>
				</div>
			{/if}
		{/if}
	</div>

	<!-- Input -->
	<AiChatInput bind:this={chatInputRef} />
</aside>
