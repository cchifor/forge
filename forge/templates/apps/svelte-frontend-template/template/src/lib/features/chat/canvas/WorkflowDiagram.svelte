<script lang="ts">
	import type { WorkspaceActivity } from '../chat.types';

	let { activity }: { activity: WorkspaceActivity } = $props();

	interface Node {
		id: string;
		label: string;
		status?: 'pending' | 'running' | 'done' | 'error';
	}

	interface Edge {
		from: string;
		to: string;
	}

	const nodes = $derived.by<Node[]>(() => {
		const raw = activity.content.nodes;
		return Array.isArray(raw) ? (raw as Node[]) : [];
	});
	const edges = $derived.by<Edge[]>(() => {
		const raw = activity.content.edges;
		return Array.isArray(raw) ? (raw as Edge[]) : [];
	});

	function statusColor(status?: string): string {
		switch (status) {
			case 'done':
				return 'bg-emerald-500/15 text-emerald-700 border-emerald-500/40';
			case 'running':
				return 'bg-amber-500/15 text-amber-800 border-amber-500/40';
			case 'error':
				return 'bg-red-500/15 text-red-700 border-red-500/40';
			default:
				return 'bg-muted text-muted-foreground border-border';
		}
	}
</script>

<div class="space-y-3 p-4" data-testid="canvas-workflow">
	<p class="text-xs text-muted-foreground">
		Workflow ({nodes.length} node{nodes.length === 1 ? '' : 's'}, {edges.length} edge{edges.length === 1 ? '' : 's'})
	</p>
	<div class="flex flex-wrap items-center gap-2">
		{#each nodes as node, i (node.id)}
			<div
				class="rounded-md border px-3 py-1.5 text-xs font-medium {statusColor(node.status)}"
				data-node-id={node.id}
				data-status={node.status ?? 'pending'}
			>
				{node.label}
			</div>
			{#if i < nodes.length - 1}
				<span aria-hidden="true" class="text-muted-foreground">→</span>
			{/if}
		{/each}
	</div>
	{#if edges.length > 0}
		<details>
			<summary class="cursor-pointer text-xs text-muted-foreground">Edges</summary>
			<ul class="mt-1 list-disc pl-5 text-xs">
				{#each edges as edge, i (i)}
					<li>{edge.from} → {edge.to}</li>
				{/each}
			</ul>
		</details>
	{/if}
</div>
