<script lang="ts">
	import { MessageCircle, RefreshCw, X } from 'lucide-svelte';
	import { getUiStore } from '$lib/features/shell';
	import { getChatStore } from '$lib/features/chat';
	import { APPROVAL_MODES, AVAILABLE_MODELS } from '../chat.constants';
	import AgentStatusBar from './AgentStatusBar.svelte';
	import AiChatInput from './AiChatInput.svelte';
	import AiChatMessage from './AiChatMessage.svelte';
	import UserPromptCard from './UserPromptCard.svelte';
	import type { ChatMode } from '$lib/features/shell';

	let { mode = 'inline' }: { mode?: ChatMode } = $props();

	const ui = getUiStore();
	const chat = getChatStore();

	let messagesContainer: HTMLDivElement | undefined;
	let chatInputRef: AiChatInput | undefined;

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
	data-testid="ai-chat-panel"
>
	<!-- Header -->
	<div class="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-ai-border px-3">
		<div class="flex min-w-0 items-center gap-2">
			<MessageCircle class="h-4 w-4 shrink-0 text-ai-accent" aria-hidden="true" />
			<select
				class="rounded border border-input bg-background px-1.5 py-0.5 text-xs font-medium focus:outline-none"
				value={chat.model}
				onchange={(e) => chat.setModel(e.currentTarget.value as typeof chat.model)}
				aria-label="Model"
				data-testid="model-select"
			>
				{#each AVAILABLE_MODELS as m (m.id)}
					<option value={m.id}>{m.label}</option>
				{/each}
			</select>
			<select
				class="rounded border border-input bg-background px-1.5 py-0.5 text-xs focus:outline-none"
				value={chat.approvalMode}
				onchange={(e) => chat.setApprovalMode(e.currentTarget.value as typeof chat.approvalMode)}
				aria-label="Approval mode"
				data-testid="approval-select"
			>
				{#each APPROVAL_MODES as a (a.id)}
					<option value={a.id}>{a.label}</option>
				{/each}
			</select>
		</div>
		<div class="flex items-center gap-1">
			<span
				class="hidden rounded-full bg-ai-surface px-2.5 py-0.5 text-xs text-ai-surface-foreground sm:inline"
			>
				{chat.contextLabel}
			</span>
			<button
				class="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
				onclick={() => chat.clearMessages()}
				aria-label="New thread"
				title="New thread"
				data-testid="new-thread-button"
			>
				<RefreshCw class="h-4 w-4" />
			</button>
			<button
				class="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
				onclick={() => ui.closeChat()}
				aria-label="Close AI Chat"
			>
				<X class="h-4 w-4" />
			</button>
		</div>
	</div>

	<!-- Messages -->
	<div
		bind:this={messagesContainer}
		class="flex-1 space-y-4 overflow-y-auto p-4"
		data-testid="messages-list"
	>
		{#if chat.messages.length === 0}
			<div class="flex h-full flex-col items-center justify-center px-6 text-center">
				<div class="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-ai-surface">
					<MessageCircle class="h-6 w-6 text-ai-accent" />
				</div>
				<h3 class="mb-1 text-sm font-medium">How can I help?</h3>
				<p class="text-xs text-muted-foreground">
					Ask a question or describe what you need help with.
				</p>
			</div>
		{:else}
			{#each chat.messages as message, idx (message.id)}
				<AiChatMessage
					{message}
					toolCalls={idx === chat.messages.length - 1 ? chat.activeToolCalls : []}
				/>
			{/each}
			{#if chat.pendingPrompt}
				<UserPromptCard prompt={chat.pendingPrompt} onRespond={chat.respondToPrompt} />
			{/if}
			{#if chat.error}
				<div
					class="rounded-md border border-red-500/40 bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950/40 dark:text-red-300"
					data-testid="chat-error"
				>
					{chat.error.message}
				</div>
			{/if}
			{#if chat.isGenerating}
				<div class="flex items-center gap-2 text-xs text-muted-foreground">
					<div class="flex gap-1">
						<span
							class="h-1.5 w-1.5 animate-bounce rounded-full bg-ai-accent [animation-delay:0ms]"
						></span>
						<span
							class="h-1.5 w-1.5 animate-bounce rounded-full bg-ai-accent [animation-delay:150ms]"
						></span>
						<span
							class="h-1.5 w-1.5 animate-bounce rounded-full bg-ai-accent [animation-delay:300ms]"
						></span>
					</div>
					<span>Thinking...</span>
				</div>
			{/if}
		{/if}
	</div>

	<AgentStatusBar state={chat.customState} />

	<!-- Input -->
	<AiChatInput bind:this={chatInputRef} />
</aside>
