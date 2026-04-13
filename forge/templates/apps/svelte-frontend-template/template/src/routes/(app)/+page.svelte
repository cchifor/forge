<script lang="ts">
	import { Activity, Server, Info, Package, Plus, User } from 'lucide-svelte';
	import { HealthIndicator } from '$lib/shared';
	import { createServiceInfoQuery, createReadinessQuery } from '$lib/features/dashboard';
	import { getAuth } from '$lib/core';

	const auth = getAuth();
	const infoQuery = createServiceInfoQuery();
	const readinessQuery = createReadinessQuery();
</script>

<div class="space-y-6">
	<div>
		<h1 class="text-3xl font-bold tracking-tight">
			Welcome back{auth.user?.firstName ? `, ${auth.user.firstName}` : ''}!
		</h1>
		<p class="text-muted-foreground">Here is an overview of your service</p>
	</div>

	<!-- Service Info Cards -->
	<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
		<!-- Service Card -->
		<div class="rounded-lg border bg-card text-card-foreground shadow-sm">
			<div class="flex flex-row items-center justify-between space-y-0 p-6 pb-2">
				<h3 class="text-sm font-medium">Service</h3>
				<Info class="h-4 w-4 text-muted-foreground" />
			</div>
			<div class="p-6 pt-0">
				{#if $infoQuery.isLoading}
					<div class="mb-2 h-7 w-40 animate-pulse rounded bg-muted"></div>
					<div class="h-4 w-24 animate-pulse rounded bg-muted"></div>
				{:else if $infoQuery.data}
					<div class="text-2xl font-bold">{$infoQuery.data.title}</div>
					<p class="text-xs text-muted-foreground">v{$infoQuery.data.version}</p>
				{/if}
			</div>
		</div>

		<!-- Status Card -->
		<div class="rounded-lg border bg-card text-card-foreground shadow-sm">
			<div class="flex flex-row items-center justify-between space-y-0 p-6 pb-2">
				<h3 class="text-sm font-medium">Status</h3>
				<Activity class="h-4 w-4 text-muted-foreground" />
			</div>
			<div class="p-6 pt-0">
				{#if $readinessQuery.isLoading}
					<div class="mb-2 h-7 w-20 animate-pulse rounded bg-muted"></div>
					<div class="h-4 w-32 animate-pulse rounded bg-muted"></div>
				{:else if $readinessQuery.data}
					<div class="mb-1">
						<HealthIndicator status={$readinessQuery.data.status} />
					</div>
					<p class="text-xs text-muted-foreground">
						{Object.keys($readinessQuery.data.components).length} component(s) checked
					</p>
				{/if}
			</div>
		</div>

		<!-- Quick Actions Card -->
		<div class="rounded-lg border bg-card text-card-foreground shadow-sm">
			<div class="flex flex-row items-center justify-between space-y-0 p-6 pb-2">
				<h3 class="text-sm font-medium">Quick Actions</h3>
				<Package class="h-4 w-4 text-muted-foreground" />
			</div>
			<div class="p-6 pt-0">
				<div class="flex flex-wrap gap-2">
					<!-- --- feature action chips --- -->
					<a
						href="/profile"
						class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm hover:bg-accent transition-colors"
					>
						<User class="h-3.5 w-3.5" /> View Profile
					</a>
				</div>
			</div>
		</div>
	</div>

	<!-- Health Components -->
	{#if $readinessQuery.data?.components}
		<div class="rounded-lg border bg-card text-card-foreground shadow-sm">
			<div class="p-6">
				<h3 class="flex items-center gap-2 text-lg font-semibold leading-none tracking-tight">
					<Server class="h-5 w-5" />
					Health Components
				</h3>
				<p class="mt-1.5 text-sm text-muted-foreground">
					Real-time status of service dependencies
				</p>
			</div>
			<div class="p-6 pt-0">
				<div class="space-y-3">
					{#each Object.entries($readinessQuery.data.components) as [name, component]}
						<div class="flex items-center justify-between rounded-lg border p-3">
							<div>
								<p class="font-medium capitalize">{name}</p>
								{#if component.latency_ms != null}
									<p class="text-xs text-muted-foreground">
										{component.latency_ms.toFixed(1)}ms latency
									</p>
								{/if}
							</div>
							<HealthIndicator status={component.status} />
						</div>
					{/each}
				</div>
			</div>
		</div>
	{/if}

	<!-- System Info -->
	{#if $readinessQuery.data?.system_info}
		<div class="rounded-lg border bg-card text-card-foreground shadow-sm">
			<div class="p-6">
				<h3 class="text-lg font-semibold leading-none tracking-tight">System Information</h3>
			</div>
			<div class="p-6 pt-0">
				<dl class="grid grid-cols-1 gap-2 sm:grid-cols-2">
					{#each Object.entries($readinessQuery.data.system_info) as [key, value]}
						<div class="flex flex-col rounded-lg border p-3">
							<dt class="text-xs capitalize text-muted-foreground">
								{key.replace(/_/g, ' ')}
							</dt>
							<dd class="text-sm font-medium">{value}</dd>
						</div>
					{/each}
				</dl>
			</div>
		</div>
	{/if}
</div>
