<script lang="ts">
	import type { AgentState } from '../chat.types';

	let { state }: { state: AgentState } = $props();

	const cost = $derived(state.cost);
	const ctx = $derived(state.context);
	const todoCount = $derived((state.todos ?? []).length);
	const usagePct = $derived(ctx ? Math.round(ctx.usage_pct) : 0);
</script>

<div
	class="flex items-center justify-between gap-3 border-t border-border/40 bg-muted/30 px-3 py-1.5 text-[11px] text-muted-foreground"
	data-testid="agent-status-bar"
>
	<div class="flex items-center gap-3">
		{#if cost}
			<span title="Total cost across all runs">
				${cost.total_usd.toFixed(4)}
			</span>
			<span title="Tokens consumed in current run">
				{cost.run_tokens.toLocaleString()} tok
			</span>
		{/if}
		{#if todoCount > 0}
			<span title="Pending agent todos">
				{todoCount} todo{todoCount === 1 ? '' : 's'}
			</span>
		{/if}
	</div>
	{#if ctx}
		<div class="flex items-center gap-2" title="Context window utilization">
			<span>{usagePct}% ctx</span>
			<div class="h-1.5 w-16 overflow-hidden rounded-full bg-border">
				<div
					class="h-full bg-primary transition-all"
					style:width="{Math.min(100, usagePct)}%"
				></div>
			</div>
		</div>
	{/if}
</div>
