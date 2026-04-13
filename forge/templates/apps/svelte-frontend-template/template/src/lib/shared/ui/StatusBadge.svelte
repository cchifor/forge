<script lang="ts">
	import { CheckCircle, Edit, Archive } from 'lucide-svelte';

	let { status }: { status: string } = $props();

	const config = $derived(
		status === 'ACTIVE'
			? {
					icon: CheckCircle,
					class:
						'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400'
				}
			: status === 'DRAFT'
				? {
						icon: Edit,
						class: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400'
					}
				: {
						icon: Archive,
						class: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
					}
	);
</script>

<span
	class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium {config.class}"
>
	<config.icon class="h-3 w-3" />
	{status}
</span>
