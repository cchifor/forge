<script lang="ts">
	import type { UserPromptPayload } from '../chat.types';

	let {
		prompt,
		onRespond
	}: { prompt: UserPromptPayload; onRespond: (answer: string) => void } = $props();
</script>

<div
	class="rounded-lg border border-amber-500/30 bg-amber-50 p-3 text-sm dark:bg-amber-950/40"
	role="dialog"
	aria-labelledby="prompt-question"
	data-testid="user-prompt-card"
>
	<p id="prompt-question" class="mb-2 font-medium text-amber-900 dark:text-amber-200">
		{prompt.question}
	</p>
	<div class="flex flex-wrap gap-2">
		{#each prompt.options as opt (opt.label)}
			<button
				type="button"
				onclick={() => onRespond(opt.label)}
				class="rounded-md border border-amber-400 bg-white px-3 py-1.5 text-xs font-medium text-amber-900 transition hover:bg-amber-100 dark:bg-amber-900/40 dark:text-amber-100 dark:hover:bg-amber-900/60"
				title={opt.description}
				data-recommended={opt.recommended}
			>
				{opt.label}
				{#if opt.recommended}
					<span class="ml-1 text-[10px] uppercase tracking-wide text-amber-600">recommended</span>
				{/if}
			</button>
		{/each}
	</div>
</div>
