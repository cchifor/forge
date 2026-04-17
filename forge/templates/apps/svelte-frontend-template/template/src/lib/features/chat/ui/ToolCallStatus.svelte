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
</script>

<div
	class="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium {variant.classes}"
	data-testid="tool-call-status"
	data-tool-name={toolCall.name}
	data-status={toolCall.status}
>
	<variant.Icon
		class="h-3 w-3 {toolCall.status === 'running' ? 'animate-spin' : ''}"
		aria-hidden="true"
	/>
	<span>{toolCall.name}</span>
</div>
