<script lang="ts">
	import type { WorkspaceActivity } from '../chat.types';

	let { activity }: { activity: WorkspaceActivity } = $props();

	const code = $derived(typeof activity.content.code === 'string' ? activity.content.code : '');
	const language = $derived(
		typeof activity.content.language === 'string' ? activity.content.language : 'text'
	);
	const filename = $derived(
		typeof activity.content.filename === 'string' ? activity.content.filename : ''
	);

	function copy() {
		void navigator.clipboard.writeText(code);
	}
</script>

<div class="flex h-full flex-col" data-testid="canvas-code-viewer">
	<div class="flex items-center justify-between border-b border-border px-3 py-2">
		<div class="flex items-center gap-2 text-xs">
			{#if filename}
				<span class="font-mono">{filename}</span>
			{/if}
			<span class="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
				{language}
			</span>
		</div>
		<button
			type="button"
			class="rounded-md border border-input px-2 py-1 text-[11px] hover:bg-muted"
			onclick={copy}
		>
			Copy
		</button>
	</div>
	<pre
		class="m-0 flex-1 overflow-auto bg-muted/40 p-3 font-mono text-xs leading-relaxed"
	>{code}</pre>
</div>
