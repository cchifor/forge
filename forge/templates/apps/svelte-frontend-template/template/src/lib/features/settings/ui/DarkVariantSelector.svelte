<script lang="ts">
	let {
		value,
		onchange,
		disabled = false
	}: {
		value: string;
		onchange: (v: string) => void;
		disabled?: boolean;
	} = $props();

	const options = [
		{ value: 'standard', label: 'Standard' },
		{ value: 'oled', label: 'OLED' }
	];
</script>

<div
	class="inline-flex items-center rounded-lg border bg-muted p-1 {disabled
		? 'opacity-50 pointer-events-none'
		: ''}"
>
	{#each options as option}
		<button
			class="inline-flex items-center rounded-md px-3 py-1.5 text-sm font-medium transition-colors {value ===
			option.value
				? 'bg-background text-foreground shadow-sm'
				: 'text-muted-foreground hover:text-foreground'}"
			onclick={() => onchange(option.value)}
			{disabled}
		>
			{option.label}
		</button>
	{/each}
</div>
