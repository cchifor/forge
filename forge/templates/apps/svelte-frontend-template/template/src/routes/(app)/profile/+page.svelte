<script lang="ts">
	import { User, Mail, Shield, Building2, Hash } from 'lucide-svelte';
	import { getAuth } from '$lib/core';

	const auth = getAuth();

	const initials = $derived(
		auth.user
			? ((auth.user.firstName?.[0] ?? '') + (auth.user.lastName?.[0] ?? '')).toUpperCase() || '?'
			: '?'
	);

	const profileFields = $derived(
		auth.user
			? [
					{ icon: User, label: 'Username', value: auth.user.username },
					{ icon: Mail, label: 'Email', value: auth.user.email },
					{ icon: Hash, label: 'User ID', value: auth.user.id },
					{ icon: Building2, label: 'Customer ID', value: auth.user.customerId },
					{ icon: Building2, label: 'Organization', value: auth.user.orgId ?? 'N/A' }
				]
			: []
	);
</script>

<div class="space-y-6">
	<div>
		<h1 class="text-3xl font-bold tracking-tight">Profile</h1>
		<p class="text-muted-foreground">
			Your account information from the authentication provider
		</p>
	</div>

	<div class="grid gap-6 md:grid-cols-3">
		<!-- Avatar Card -->
		<div class="rounded-lg border bg-card text-card-foreground shadow-sm md:col-span-1">
			<div class="flex flex-col items-center p-6">
				<div
					class="flex h-24 w-24 items-center justify-center rounded-full bg-muted text-2xl font-medium"
				>
					{initials}
				</div>
				<h2 class="mt-4 text-xl font-semibold">
					{auth.user?.firstName}
					{auth.user?.lastName}
				</h2>
				<p class="text-sm text-muted-foreground">{auth.user?.email}</p>
				<div class="my-4 h-px w-full bg-border"></div>
				<div class="flex flex-wrap gap-2">
					{#each auth.user?.roles ?? [] as role}
						<span
							class="inline-flex items-center gap-1 rounded-full border bg-secondary px-2.5 py-0.5 text-xs font-semibold text-secondary-foreground"
						>
							<Shield class="h-3 w-3" />
							{role}
						</span>
					{/each}
				</div>
			</div>
		</div>

		<!-- Details Card -->
		<div class="rounded-lg border bg-card text-card-foreground shadow-sm md:col-span-2">
			<div class="p-6">
				<h3 class="text-lg font-semibold leading-none tracking-tight">Account Details</h3>
				<p class="mt-1.5 text-sm text-muted-foreground">
					Information extracted from your JWT token
				</p>
			</div>
			<div class="p-6 pt-0">
				<dl class="space-y-4">
					{#each profileFields as field}
						<div class="flex items-start gap-3">
							<div
								class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted"
							>
								<field.icon class="h-4 w-4 text-muted-foreground" />
							</div>
							<div>
								<dt class="text-sm text-muted-foreground">{field.label}</dt>
								<dd class="break-all text-sm font-medium">{field.value}</dd>
							</div>
						</div>
					{/each}
				</dl>
			</div>
		</div>
	</div>
</div>
