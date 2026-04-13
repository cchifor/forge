<script lang="ts">
	import { page } from '$app/stores';
	import { invalidateAll } from '$app/navigation';
	import { AlertTriangle } from 'lucide-svelte';
	import { userFacingMessage, categorizeError } from '$lib/core/errors';

	const message = $derived(userFacingMessage($page.status, $page.error?.message));
	const isServer = $derived(categorizeError($page.status) === 'server');
</script>

<div class="flex flex-col items-center justify-center gap-4 py-16 text-center px-4">
	<AlertTriangle class="h-12 w-12 text-muted-foreground" />
	<h2 class="text-2xl font-bold">{$page.status}</h2>
	<p class="text-muted-foreground max-w-md">{message}</p>
	<div class="flex gap-2">
		{#if isServer}
			<button
				class="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
				onclick={() => invalidateAll()}
			>
				Try Again
			</button>
		{/if}
		<a
			href="/"
			class="inline-flex h-9 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
		>
			Back to Dashboard
		</a>
	</div>
</div>
