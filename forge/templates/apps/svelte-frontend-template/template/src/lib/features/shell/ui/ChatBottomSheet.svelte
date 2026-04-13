<script lang="ts">
	import type { Snippet } from 'svelte';

	let { open = $bindable(false), children }: { open: boolean; children: Snippet } = $props();

	function dismiss() {
		open = false;
	}
</script>

{#if open}
	<!-- Backdrop -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-50 bg-black/50"
		onclick={dismiss}
		onkeydown={(e) => e.key === 'Escape' && dismiss()}
	></div>

	<!-- Bottom sheet -->
	<div class="fixed bottom-0 left-0 z-50 flex w-full flex-col rounded-t-2xl bg-background shadow-xl" style="height: 90vh">
		<!-- Drag handle -->
		<div class="flex justify-center py-3">
			<div class="h-1 w-10 rounded-full bg-muted-foreground/30"></div>
		</div>
		{@render children()}
	</div>
{/if}
