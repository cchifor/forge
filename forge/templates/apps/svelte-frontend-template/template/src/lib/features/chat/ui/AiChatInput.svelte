<script lang="ts">
	import { Mic, Paperclip, Send, X } from 'lucide-svelte';
	import { getChatStore } from '$lib/features/chat';
	import type { ChatAttachment } from '$lib/features/chat/chat.types';
	import {
		ChatAttachmentUploadError,
		uploadChatAttachment
	} from '$lib/features/chat/model/chat-attachments';
	import { cn } from '$lib/shared/lib/utils';

	const chat = getChatStore();
	let inputValue = $state('');
	let textareaEl: HTMLTextAreaElement | undefined;
	let fileInputEl: HTMLInputElement | undefined;
	let attachments = $state<ChatAttachment[]>([]);
	let uploading = $state(false);
	let uploadError = $state<string | null>(null);

	export function focusInput() {
		textareaEl?.focus();
	}

	function handleSubmit() {
		const trimmed = inputValue.trim();
		// Allow attachment-only sends; chat.svelte.ts enforces the
		// "must have either text or attachments" invariant.
		if ((!trimmed && attachments.length === 0) || chat.isGenerating) return;
		const ids = attachments.map((a) => a.id);
		chat.addUserMessage(trimmed, { attachmentIds: ids });
		inputValue = '';
		attachments = [];
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

	function openFilePicker() {
		uploadError = null;
		fileInputEl?.click();
	}

	async function handleFiles(files: FileList | null | undefined) {
		if (!files || files.length === 0) return;
		uploading = true;
		uploadError = null;
		try {
			// Upload sequentially so backend pressure stays bounded and
			// error attribution is straightforward. Most users attach
			// 1-3 files per turn — parallelism wouldn't move the needle.
			for (const file of Array.from(files)) {
				const chip = await uploadChatAttachment(file);
				attachments = [...attachments, chip];
			}
		} catch (err) {
			if (err instanceof ChatAttachmentUploadError) {
				uploadError = err.message;
			} else {
				uploadError = `Upload failed: ${err instanceof Error ? err.message : String(err)}`;
			}
		} finally {
			uploading = false;
			// Reset the input so re-picking the same file fires `change`
			// again — browsers swallow repeat selections of an unchanged
			// value otherwise.
			if (fileInputEl) fileInputEl.value = '';
		}
	}

	function removeAttachment(id: string) {
		attachments = attachments.filter((a) => a.id !== id);
	}

	function formatBytes(n: number | undefined): string {
		if (!n || n <= 0) return '';
		if (n < 1024) return `${n}B`;
		if (n < 1024 * 1024) return `${Math.round(n / 1024)}KB`;
		return `${(n / (1024 * 1024)).toFixed(1)}MB`;
	}
</script>

<div class="border-t border-ai-border p-3">
	{#if attachments.length > 0 || uploading || uploadError}
		<div
			class="mb-2 flex flex-wrap items-center gap-2"
			data-testid="chat-attachments"
		>
			{#each attachments as att (att.id)}
				<span
					class="inline-flex items-center gap-1.5 rounded-full border border-input bg-muted/40 px-2 py-1 text-xs"
					title={`${att.filename}${att.size_bytes ? ` (${formatBytes(att.size_bytes)})` : ''}`}
				>
					<span class="max-w-[160px] truncate">{att.filename}</span>
					{#if att.size_bytes}
						<span class="text-muted-foreground">· {formatBytes(att.size_bytes)}</span>
					{/if}
					<button
						type="button"
						class="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
						aria-label={`Remove ${att.filename}`}
						onclick={() => removeAttachment(att.id)}
					>
						<X class="h-3 w-3" />
					</button>
				</span>
			{/each}
			{#if uploading}
				<span class="text-xs text-muted-foreground">Uploading…</span>
			{/if}
			{#if uploadError}
				<span class="text-xs text-destructive" role="alert">{uploadError}</span>
			{/if}
		</div>
	{/if}

	<input
		bind:this={fileInputEl}
		type="file"
		multiple
		class="hidden"
		onchange={(e) => handleFiles((e.target as HTMLInputElement).files)}
		data-testid="chat-file-input"
	/>

	<div
		class={cn(
			'flex items-end gap-2 rounded-lg border bg-background p-2',
			chat.isGenerating ? 'ai-glow-pulse border-ai-accent/50' : 'border-input'
		)}
	>
		<button
			type="button"
			class="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
			title="Attach file"
			aria-label="Attach file"
			onclick={openFilePicker}
			disabled={uploading || chat.isGenerating}
			data-testid="chat-attach"
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
				inputValue.trim() || attachments.length > 0
					? 'bg-ai-accent text-ai-accent-foreground hover:bg-ai-accent/90'
					: 'text-muted-foreground'
			)}
			onclick={handleSubmit}
			disabled={(!inputValue.trim() && attachments.length === 0) || chat.isGenerating}
			aria-label="Send message"
			data-testid="chat-send"
		>
			<Send class="h-4 w-4" />
		</button>
	</div>
</div>
