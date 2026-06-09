<script lang="ts">
	let {
		value,
		onchange
	}: {
		value: string;
		onchange: (v: string) => void;
	} = $props();

	const options = [
		{ value: 'sm', label: 'Small' },
		{ value: 'md', label: 'Medium' },
		{ value: 'lg', label: 'Large' }
	];
</script>

<div class="inline-flex items-center rounded-lg border bg-muted p-1">
	{#each options as option}
		<button
			class="inline-flex items-center rounded-md px-3 py-1.5 text-sm font-medium transition-colors {value ===
			option.value
				? 'bg-background text-foreground shadow-sm'
				: 'text-muted-foreground hover:text-foreground'}"
			onclick={() => onchange(option.value)}
		>
			{option.label}
		</button>
	{/each}
</div>
