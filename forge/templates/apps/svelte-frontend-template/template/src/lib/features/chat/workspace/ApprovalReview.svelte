<script lang="ts">
	import type { WorkspaceAction, WorkspaceActivity } from '../chat.types';

	let {
		activity,
		onAction
	}: { activity: WorkspaceActivity; onAction?: (a: WorkspaceAction) => void } = $props();

	const summary = $derived(
		typeof activity.content.summary === 'string' ? activity.content.summary : ''
	);
	const diff = $derived(
		typeof activity.content.diff === 'string' ? activity.content.diff : ''
	);
	const items = $derived.by<string[]>(() => {
		const raw = activity.content.items;
		return Array.isArray(raw) ? (raw as string[]) : [];
	});

	function approve() {
		onAction?.({ type: 'submit', data: { decision: 'approve' } });
	}
	function reject() {
		onAction?.({ type: 'submit', data: { decision: 'reject' } });
	}
</script>

<div class="flex flex-col gap-3 p-4" data-testid="approval-review">
	<h4 class="text-sm font-semibold">Review &amp; approve</h4>
	{#if summary}
		<p class="text-sm text-muted-foreground">{summary}</p>
	{/if}
	{#if items.length > 0}
		<ul class="space-y-1 text-sm">
			{#each items as item, i (i)}
				<li class="flex items-start gap-2">
					<span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary"></span>
					<span class="break-words">{item}</span>
				</li>
			{/each}
		</ul>
	{/if}
	{#if diff}
		<pre
			class="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs whitespace-pre-wrap break-all"
		>{diff}</pre>
	{/if}
	<div class="flex gap-2">
		<button
			type="button"
			onclick={approve}
			class="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
		>Approve</button>
		<button
			type="button"
			onclick={reject}
			class="rounded-md border border-input px-3 py-1.5 text-xs font-medium hover:bg-muted"
		>Reject</button>
	</div>
</div>
