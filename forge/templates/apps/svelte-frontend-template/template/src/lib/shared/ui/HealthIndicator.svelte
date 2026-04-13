<script lang="ts">
	let { status }: { status: string } = $props();

	const variant = $derived(
		status === 'UP' ? 'default' : status === 'DEGRADED' ? 'secondary' : 'destructive'
	);

	const dotColor = $derived(
		status === 'UP'
			? 'bg-emerald-500'
			: status === 'DEGRADED'
				? 'bg-amber-500'
				: status === 'DOWN'
					? 'bg-red-500'
					: 'bg-gray-400'
	);

	const badgeClass = $derived(
		variant === 'default'
			? 'border-transparent bg-primary text-primary-foreground'
			: variant === 'secondary'
				? 'border-transparent bg-secondary text-secondary-foreground'
				: 'border-transparent bg-destructive text-destructive-foreground'
	);
</script>

<span
	class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold {badgeClass}"
>
	<span class="h-2 w-2 rounded-full {dotColor}"></span>
	{status}
</span>
