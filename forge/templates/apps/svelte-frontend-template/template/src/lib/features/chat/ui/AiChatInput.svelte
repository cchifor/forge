<script lang="ts">
	import { Mic, Paperclip, Send } from 'lucide-svelte';
	import { getChatStore } from '$lib/features/chat';
	import { cn } from '$lib/shared/lib/utils';

	const chat = getChatStore();
	let inputValue = $state('');
	let textareaEl: HTMLTextAreaElement | undefined;

	export function focusInput() {
		textareaEl?.focus();
	}

	function handleSubmit() {
		const trimmed = inputValue.trim();
		if (!trimmed || chat.isGenerating) return;
		chat.addUserMessage(trimmed);
		inputValue = '';
		if (textareaEl) textareaEl.style.height = 'auto';
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSubmit();
		}
	}

	function handleInput() {
		if (textareaEl) {
			textareaEl.style.height = 'auto';
			textareaEl.style.height = Math.min(textareaEl.scrollHeight, 120) + 'px';
		}
	}
</script>

<div class="border-t border-ai-border p-3">
	<div
		class={cn(
			'flex items-end gap-2 rounded-lg border bg-background p-2',
			chat.isGenerating ? 'ai-glow-pulse border-ai-accent/50' : 'border-input'
		)}
	>
		<button
			class="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
			title="Attach file"
			aria-label="Attach file"
			disabled
		>
			<Paperclip class="h-4 w-4" />
		</button>

		<textarea
			bind:this={textareaEl}
			bind:value={inputValue}
			oninput={handleInput}
			onkeydown={handleKeydown}
			placeholder="Ask anything..."
			rows="1"
			class="flex-1 resize-none bg-transparent text-sm leading-[1.6] placeholder:text-muted-foreground focus:outline-none"
			aria-label="Chat message input"
			disabled={chat.isGenerating}
			data-testid="chat-input"
		></textarea>

		<button
			class="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
			title="Voice input"
			aria-label="Voice input"
			disabled
		>
			<Mic class="h-4 w-4" />
		</button>

		<button
			class={cn(
				'shrink-0 rounded-md p-1.5 transition-colors',
				inputValue.trim()
					? 'bg-ai-accent text-ai-accent-foreground hover:bg-ai-accent/90'
					: 'text-muted-foreground'
			)}
			onclick={handleSubmit}
			disabled={!inputValue.trim() || chat.isGenerating}
			aria-label="Send message"
			data-testid="chat-send"
		>
			<Send class="h-4 w-4" />
		</button>
	</div>
</div>
