<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { Shield, LogIn } from 'lucide-svelte';
	import { getAuth } from '$lib/core';
	import { onMount } from 'svelte';

	const auth = getAuth();
	const authDisabled = import.meta.env.VITE_AUTH_DISABLED === 'true';

	onMount(() => {
		if (auth.isAuthenticated) {
			const redirect = $page.url.searchParams.get('redirect') || '/';
			goto(redirect, { replaceState: true });
		}
	});

	function handleLogin() {
		const redirect = $page.url.searchParams.get('redirect') || '/';
		if (authDisabled) {
			auth.login();
			goto(redirect, { replaceState: true });
		} else {
			auth.login(redirect);
		}
	}
</script>

<div class="flex min-h-svh items-center justify-center bg-muted p-4">
	<div class="w-full max-w-sm rounded-lg border bg-card text-card-foreground shadow-sm">
		<div class="flex flex-col items-center space-y-1.5 p-6 text-center">
			<div
				class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground"
			>
				<Shield class="h-6 w-6" />
			</div>
			<h3 class="text-2xl font-semibold leading-none tracking-tight">Welcome back</h3>
			<p class="text-sm text-muted-foreground">Sign in to access the dashboard</p>
		</div>

		<div class="p-6 pt-0">
			<button
				class="inline-flex h-11 w-full items-center justify-center gap-2 whitespace-nowrap rounded-md bg-primary px-8 text-sm font-medium text-primary-foreground ring-offset-background transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
				onclick={handleLogin}
			>
				<LogIn class="h-4 w-4" />
				Sign in
			</button>
		</div>

		{#if authDisabled}
			<div class="flex items-center justify-center p-6 pt-0">
				<span
					class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold bg-secondary text-secondary-foreground"
				>
					<span class="h-2 w-2 rounded-full bg-amber-500"></span>
					Dev Mode - Auth Disabled
				</span>
			</div>
		{/if}
	</div>
</div>
