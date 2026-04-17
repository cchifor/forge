<script lang="ts">
	import type { WorkspaceAction, WorkspaceActivity } from '../chat.types';

	let {
		activity,
		onAction
	}: { activity: WorkspaceActivity; onAction?: (a: WorkspaceAction) => void } = $props();

	interface PromptOption {
		label: string;
		description?: string;
		recommended?: string;
	}

	const question = $derived(
		typeof activity.content.question === 'string' ? activity.content.question : 'Question'
	);
	const options = $derived.by<PromptOption[]>(() => {
		const raw = activity.content.options;
		return Array.isArray(raw) ? (raw as PromptOption[]) : [];
	});
</script>

<div class="flex flex-col gap-3 p-4" data-testid="user-prompt-review">
	<p class="text-sm font-medium">{question}</p>
	<div class="flex flex-col gap-2">
		{#each options as opt (opt.label)}
			<button
				type="button"
				onclick={() => onAction?.({ type: 'submit', data: { answer: opt.label } })}
				class="rounded-md border border-input px-3 py-2 text-left text-sm hover:bg-muted"
			>
				<span class="font-medium">{opt.label}</span>
				{#if opt.description}
					<p class="text-xs text-muted-foreground">{opt.description}</p>
				{/if}
			</button>
		{/each}
	</div>
</div>
