<script lang="ts">
	let {
		ondragmove,
		onreset
	}: {
		ondragmove?: (clientX: number) => void;
		onreset?: () => void;
	} = $props();

	let isDragging = $state(false);

	function handlePointerDown(e: PointerEvent) {
		isDragging = true;
		const target = e.currentTarget as HTMLElement;
		target.setPointerCapture(e.pointerId);
	}

	function handlePointerMove(e: PointerEvent) {
		if (!isDragging) return;
		ondragmove?.(e.clientX);
	}

	function handlePointerUp(e: PointerEvent) {
		isDragging = false;
		const target = e.currentTarget as HTMLElement;
		target.releasePointerCapture(e.pointerId);
	}

	function handleDblClick() {
		onreset?.();
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="flex w-2 shrink-0 cursor-col-resize items-center justify-center transition-colors {isDragging
		? 'bg-primary/30'
		: 'hover:bg-border'}"
	onpointerdown={handlePointerDown}
	onpointermove={handlePointerMove}
	onpointerup={handlePointerUp}
	ondblclick={handleDblClick}
	role="separator"
	aria-orientation="vertical"
>
	<div class="h-full w-px bg-border"></div>
</div>
