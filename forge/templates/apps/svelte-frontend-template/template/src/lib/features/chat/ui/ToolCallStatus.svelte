<script lang="ts">
	import { CheckCircle2, CircleX, Loader2 } from 'lucide-svelte';
	import type { ToolCallInfo } from '../chat.types';

	let { toolCall }: { toolCall: ToolCallInfo } = $props();

	const variant = $derived.by(() => {
		switch (toolCall.status) {
			case 'completed':
				return {
					classes: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
					Icon: CheckCircle2
				};
			case 'error':
				return {
					classes: 'bg-red-500/10 text-red-700 dark:text-red-300 border-red-500/30',
					Icon: CircleX
				};
			default:
				return {
					classes: 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30',
					Icon: Loader2
				};
		}
	});

	// Pillar G.2: collapsible args preview. While streaming we show the
	// raw buffer with newlines stripped — the model often emits a
	// partial JSON like `{"foo":\n  "bar"` and the embedded newlines
	// push the preview taller than it needs to be. On END, ``argsPretty``
	// takes over and we want the indentation back.
	const displayArgs = $derived.by(() => {
		if (toolCall.argsPretty && toolCall.argsPretty.length > 0) {
			return toolCall.argsPretty;
		}
		if (toolCall.argsBuffer && toolCall.argsBuffer.length > 0) {
			return toolCall.argsBuffer.replace(/\n+/g, ' ');
		}
		return '';
	});
</script>

<div
	class="inline-flex flex-col items-stretch gap-0 overflow-hidden rounded-md border text-xs font-medium {variant.classes}"
	data-testid="tool-call-status"
	data-tool-name={toolCall.name}
	data-status={toolCall.status}
>
	<div class="inline-flex items-center gap-1.5 px-2 py-0.5">
		<variant.Icon
			class="h-3 w-3 {toolCall.status === 'running' ? 'animate-spin' : ''}"
			aria-hidden="true"
		/>
		<span>{toolCall.name}</span>
	</div>
	{#if displayArgs.length > 0}
		<!-- Native <details> so we get collapse-state without JS state.
		     Cross-stack consistency with Vue (<details>) and Flutter
		     (ExpansionTile). Default-closed to keep the message column
		     compact for runs with many tool calls. -->
		<details class="border-t border-current/20" data-testid="tool-call-args">
			<summary
				class="cursor-pointer px-2 py-0.5 text-[10px] uppercase tracking-wider opacity-70 hover:opacity-100"
			>
				args
			</summary>
			<pre
				class="max-h-48 overflow-auto whitespace-pre-wrap break-all bg-background/30 px-2 py-1 font-mono text-[11px] text-foreground"
				data-testid="tool-call-args-body">{displayArgs}</pre>
		</details>
	{/if}
</div>
