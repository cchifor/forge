<script lang="ts">
	import { page } from '$app/stores';
	import { invalidateAll } from '$app/navigation';
	import { FileQuestion, ShieldAlert, ServerCrash, AlertTriangle } from 'lucide-svelte';
	import { categorizeError, userFacingMessage } from '$lib/core/errors';

	const category = $derived(categorizeError($page.status));
	const message = $derived(userFacingMessage($page.status, $page.error?.message));

	const Icon = $derived(
		category === 'not-found'
			? FileQuestion
			: category === 'forbidden'
				? ShieldAlert
				: category === 'server'
					? ServerCrash
					: AlertTriangle
	);
</script>

<div class="flex min-h-svh flex-col items-center justify-center gap-4 text-center px-4">
	<Icon class="h-16 w-16 text-muted-foreground" />
	<h1 class="text-4xl font-bold">{$page.status}</h1>
	<p class="text-lg text-muted-foreground max-w-md">{message}</p>
	<div class="flex gap-2">
		{#if category === 'server'}
			<button
				class="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
				onclick={() => invalidateAll()}
			>
				Try Again
			</button>
		{/if}
		<a
			href="/"
			class="inline-flex h-10 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
		>
			Back to Home
		</a>
	</div>
</div>
