<script lang="ts">
	import type { Component } from 'svelte';
	import { page } from '$app/stores';
	import { Settings, LogOut, UserCircle } from 'lucide-svelte';
	import { Popover } from 'bits-ui';
	import { getAuth } from '$lib/core/auth/auth.svelte';

	interface RailItem {
		title: string;
		url: string;
		icon: Component;
	}

	let { items }: { items: RailItem[] } = $props();

	const auth = getAuth();

	function isActive(url: string) {
		if (url === '/') return $page.url.pathname === '/';
		return $page.url.pathname.startsWith(url);
	}

	const userInitials = $derived(
		auth.user
			? ((auth.user.firstName?.[0] ?? '') + (auth.user.lastName?.[0] ?? '')).toUpperCase() ||
					auth.user.username[0]?.toUpperCase() ||
					'?'
			: '?'
	);
</script>

<!--
	Slim icon-only nav rail (medium tier). Mirrors AppSidebar's primary-nav
	contract but in a 72px-wide icon column; the brand mark sits on top, the
	account popover anchors the bottom.
-->
<aside
	class="flex w-[72px] shrink-0 flex-col items-center border-r bg-sidebar-background text-sidebar-foreground"
>
	<!-- Brand mark -->
	<div class="flex h-14 w-full shrink-0 items-center justify-center border-b">
		<span
			class="flex h-8 w-8 items-center justify-center rounded-lg"
			style="background: linear-gradient(135deg, hsl(var(--ai-gradient-from)), hsl(var(--ai-gradient-to)))"
		>
			<span class="text-sm font-bold text-white">S</span>
		</span>
	</div>

	<!-- Icon-only primary nav -->
	<nav class="flex flex-1 flex-col items-center gap-1 overflow-y-auto py-3 px-2" aria-label="Primary navigation">
		{#each items as item}
			<a
				href={item.url}
				title={item.title}
				aria-current={isActive(item.url) ? 'page' : undefined}
				class="btn-press group relative flex h-10 w-12 items-center justify-center rounded-xl transition-colors
					{isActive(item.url) ? 'bg-sidebar-accent text-sidebar-accent-foreground' : 'text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground'}"
			>
				{#if isActive(item.url)}
					<span class="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r bg-primary"></span>
				{/if}
				<item.icon class="h-5 w-5" />
			</a>
		{/each}
	</nav>

	<!-- Account popover at bottom -->
	<div class="shrink-0 border-t py-2 px-2">
		<Popover.Root>
			<Popover.Trigger
				class="btn-press flex h-12 w-12 items-center justify-center rounded-xl transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
				title="Account"
				aria-label="Account menu"
			>
				<span
					class="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-xs font-medium"
				>
					{userInitials}
				</span>
			</Popover.Trigger>
			<Popover.Content
				side="right"
				align="end"
				sideOffset={8}
				class="z-50 w-56 rounded-lg border bg-popover p-2 text-popover-foreground shadow-lg"
			>
				<div class="px-2 py-1.5 text-sm">
					<p class="font-medium">{auth.user?.firstName} {auth.user?.lastName}</p>
					<p class="text-xs text-muted-foreground">{auth.user?.email}</p>
				</div>
				<div class="my-1 h-px bg-border"></div>
				<a
					href="/settings"
					class="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
				>
					<Settings class="h-4 w-4" />
					Account Settings
				</a>
				<a
					href="/profile"
					class="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
				>
					<UserCircle class="h-4 w-4" />
					Preferences
				</a>
				<div class="my-1 h-px bg-border"></div>
				<button
					class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-destructive transition-colors hover:bg-accent"
					onclick={() => auth.logout()}
				>
					<LogOut class="h-4 w-4" />
					Log Out
				</button>
			</Popover.Content>
		</Popover.Root>
	</div>
</aside>
