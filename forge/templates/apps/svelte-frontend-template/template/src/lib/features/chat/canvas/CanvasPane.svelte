<script lang="ts">
	import { X } from 'lucide-svelte';
	import { getChatStore } from '$lib/features/chat';
	import { resolveCanvasComponent } from './registry';

	const chat = getChatStore();
	const activity = $derived(chat.canvasActivity);
	const entry = $derived(activity ? resolveCanvasComponent(activity.activityType) : null);
</script>

{#if activity && entry}
	<section
		class="flex h-full w-full flex-col border-l border-border bg-background"
		aria-label={entry.label}
		data-testid="canvas-pane"
		data-activity-type={activity.activityType}
	>
		<div class="flex h-12 shrink-0 items-center justify-between border-b border-border px-3">
			<h3 class="text-sm font-medium">{entry.label}</h3>
			<button
				type="button"
				onclick={() => chat.clearCanvas()}
				class="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
				aria-label="Close canvas"
			>
				<X class="h-4 w-4" />
			</button>
		</div>
		<div class="flex-1 overflow-y-auto">
			{@const Comp = entry.component}
			<Comp {activity} />
		</div>
	</section>
{/if}
