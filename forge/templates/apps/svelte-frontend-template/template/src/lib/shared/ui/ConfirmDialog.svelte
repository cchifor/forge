<script lang="ts">
	let {
		open = $bindable(false),
		title = 'Are you sure?',
		description = 'This action cannot be undone.',
		confirmLabel = 'Confirm',
		cancelLabel = 'Cancel',
		variant = 'destructive' as 'default' | 'destructive',
		onconfirm
	}: {
		open: boolean;
		title?: string;
		description?: string;
		confirmLabel?: string;
		cancelLabel?: string;
		variant?: 'default' | 'destructive';
		onconfirm?: () => void;
	} = $props();

	function handleConfirm() {
		onconfirm?.();
		open = false;
	}

	const confirmButtonClass = $derived(
		variant === 'destructive'
			? 'bg-destructive text-destructive-foreground hover:bg-destructive/90'
			: 'bg-primary text-primary-foreground hover:bg-primary/90'
	);
</script>

{#if open}
	<!-- Backdrop -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-50 bg-black/80"
		onclick={() => (open = false)}
		onkeydown={(e) => e.key === 'Escape' && (open = false)}
	></div>

	<!-- Dialog -->
	<div
		class="fixed left-1/2 top-1/2 z-50 grid w-full max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 border bg-background p-6 shadow-lg rounded-lg"
		role="dialog"
		aria-modal="true"
		aria-labelledby="dialog-title"
		aria-describedby="dialog-description"
	>
		<div class="flex flex-col space-y-1.5">
			<h2 id="dialog-title" class="text-lg font-semibold leading-none tracking-tight">
				{title}
			</h2>
			<p id="dialog-description" class="text-sm text-muted-foreground">
				{description}
			</p>
		</div>

		<div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
			<button
				class="inline-flex h-10 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium ring-offset-background transition-colors hover:bg-accent hover:text-accent-foreground"
				onclick={() => (open = false)}
			>
				{cancelLabel}
			</button>
			<button
				class="inline-flex h-10 items-center justify-center rounded-md px-4 py-2 text-sm font-medium ring-offset-background transition-colors {confirmButtonClass}"
				onclick={handleConfirm}
			>
				{confirmLabel}
			</button>
		</div>
	</div>
{/if}
