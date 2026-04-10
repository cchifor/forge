<script lang="ts">
	import { QueryClientProvider } from '@tanstack/svelte-query';
	import { Tooltip } from 'bits-ui';
	import { Toaster } from 'svelte-sonner';
	import { onMount } from 'svelte';
	import { configureApiClient, createQueryClient, getAuth } from '$lib/core';
	import { enableMockingIfNeeded } from '$lib/core/msw';
	import { getSettingsStore } from '$lib/features/settings';
	import '../app.css';

	let { children } = $props();

	const queryClient = createQueryClient();

	const auth = getAuth();
	const settings = getSettingsStore();
	let initialized = $state(false);

	onMount(async () => {
		await enableMockingIfNeeded();
		await auth.init();

		configureApiClient({
			getToken: async () => null,
			onUnauthorized: () => auth.login()
		});

		settings.applyTheme();

		window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
			if (settings.theme === 'system') {
				settings.applyTheme();
			}
		});

		initialized = true;
	});
</script>

{#if initialized}
	<Tooltip.Provider delayDuration={300}>
		<QueryClientProvider client={queryClient}>
			{@render children()}
			<Toaster position="bottom-right" expand richColors closeButton />
		</QueryClientProvider>
	</Tooltip.Provider>
{:else}
	<div class="flex min-h-svh items-center justify-center">
		<div class="flex flex-col items-center gap-2">
			<div
				class="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary"
			></div>
			<p class="text-sm text-muted-foreground">Loading...</p>
		</div>
	</div>
{/if}
