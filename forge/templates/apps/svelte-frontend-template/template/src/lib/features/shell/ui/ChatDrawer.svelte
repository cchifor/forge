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
{/if}

<!-- Drawer panel -->
<div
	class="fixed right-0 top-0 z-50 flex h-full w-[360px] flex-col bg-background shadow-xl transition-transform duration-300 ease-in-out"
	style="transform: translateX({open ? '0%' : '100%'})"
>
	{#if open}
		{@render children()}
	{/if}
</div>
