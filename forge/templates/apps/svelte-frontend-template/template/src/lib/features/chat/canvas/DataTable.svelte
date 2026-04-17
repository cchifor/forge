<script lang="ts">
	import type { WorkspaceActivity } from '../chat.types';

	let { activity }: { activity: WorkspaceActivity } = $props();

	interface ColumnDef {
		key: string;
		label?: string;
	}

	const columns = $derived.by<ColumnDef[]>(() => {
		const raw = activity.content.columns;
		if (Array.isArray(raw)) return raw as ColumnDef[];
		const rows = activity.content.rows;
		if (Array.isArray(rows) && rows[0] && typeof rows[0] === 'object') {
			return Object.keys(rows[0] as Record<string, unknown>).map((k) => ({ key: k }));
		}
		return [];
	});

	const rows = $derived.by<Array<Record<string, unknown>>>(() => {
		const raw = activity.content.rows;
		if (Array.isArray(raw)) return raw as Array<Record<string, unknown>>;
		return [];
	});

	function format(v: unknown): string {
		if (v == null) return '';
		if (typeof v === 'object') return JSON.stringify(v);
		return String(v);
	}
</script>

<div class="space-y-2 p-4" data-testid="canvas-data-table">
	{#if rows.length === 0}
		<p class="py-8 text-center text-sm text-muted-foreground">No rows.</p>
	{:else}
		<div class="overflow-x-auto rounded-md border border-border">
			<table class="min-w-full text-sm">
				<thead class="bg-muted">
					<tr>
						{#each columns as col (col.key)}
							<th class="px-3 py-2 text-left font-medium">
								{col.label ?? col.key}
							</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each rows as row, ridx (ridx)}
						<tr class="border-t border-border">
							{#each columns as col (col.key)}
								<td class="px-3 py-2 align-top">
									{format(row[col.key])}
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<p class="text-right text-[11px] text-muted-foreground">
			{rows.length} row{rows.length === 1 ? '' : 's'}
		</p>
	{/if}
</div>
