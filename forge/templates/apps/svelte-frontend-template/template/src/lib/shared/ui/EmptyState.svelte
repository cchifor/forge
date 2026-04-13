<script lang="ts">
	import { Package } from 'lucide-svelte';

	let {
		message = 'No items found',
		icon: Icon = Package as any
	}: {
		message?: string;
		icon?: any;
	} = $props();
</script>

<div class="flex flex-col items-center justify-center py-16 text-center">
	<Icon class="h-12 w-12 text-muted-foreground mb-3" />
	<p class="text-sm text-muted-foreground">{message}</p>
</div>
