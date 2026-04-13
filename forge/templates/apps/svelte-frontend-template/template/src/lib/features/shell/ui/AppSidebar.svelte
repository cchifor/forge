<script lang="ts">
	import { page } from '$app/stores';
	import {
		Home,
		FolderOpen,
		Settings,
		LogOut,
		CreditCard,
		UserCircle
	} from 'lucide-svelte';
	import { Popover } from 'bits-ui';
	import { getAuth } from '$lib/core/auth/auth.svelte';
	import { getUiStore } from '$lib/features/shell';

	let { forceCollapsed = false }: { forceCollapsed?: boolean } = $props();

	const auth = getAuth();
	const ui = getUiStore();

	const isCollapsed = $derived(forceCollapsed || ui.sidebarCollapsed);

	const navItems = [
		{ title: 'Home', url: '/', icon: Home },
		// --- feature nav items ---
	];

	function isActive(url: string) {
		if (url === '/') return $page.url.pathname === '/';
		return $page.url.pathname.startsWith(url);
	}

	function handleBrandClick() {
		if (!forceCollapsed) {
			ui.toggleSidebar();
		}
	}

	const userInitials = $derived(
		auth.user
			? ((auth.user.firstName?.[0] ?? '') + (auth.user.lastName?.[0] ?? '')).toUpperCase() ||
				auth.user.username[0]?.toUpperCase() ||
				'?'
			: '?'
	);
</script>

<aside
	class="flex flex-col border-r bg-sidebar-background text-sidebar-foreground transition-all duration-200
		{isCollapsed ? 'w-[72px]' : 'w-60'}"
>
	<!-- Top: Brand (click to expand/collapse) -->
	<button
		class="btn-press flex h-14 w-full items-center border-b px-2 transition-colors hover:bg-sidebar-accent/50"
		onclick={handleBrandClick}
		title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
	>
		<span class="flex w-14 shrink-0 items-center justify-center">
			<span
				class="flex h-8 w-8 items-center justify-center rounded-lg"
				style="background: linear-gradient(135deg, hsl(var(--ai-gradient-from)), hsl(var(--ai-gradient-to)))"
			>
				<span class="text-sm font-bold text-white">S</span>
			</span>
		</span>
		{#if !isCollapsed}
			<div class="grid flex-1 text-left text-sm leading-tight">
				<span class="truncate font-semibold">Svelte Frontend</span>
				<span class="truncate text-xs text-muted-foreground">v0.1.0</span>
			</div>
		{/if}
	</button>

	<!-- Middle: Primary Nav -->
	<nav class="flex-1 overflow-y-auto py-3 px-2">
		<ul class="space-y-1">
			{#each navItems as item}
				<li>
					<a
						href={item.url}
						class="btn-press relative flex h-10 items-center rounded-md text-sm transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground
							{isActive(item.url) ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium' : ''}"
						title={isCollapsed ? item.title : undefined}
					>
						{#if isActive(item.url)}
							<span
								class="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r bg-primary"
							></span>
						{/if}
						<span class="flex w-14 shrink-0 items-center justify-center">
							<item.icon class="h-5 w-5" />
						</span>
						{#if !isCollapsed}
							<span>{item.title}</span>
						{/if}
					</a>
				</li>
			{/each}
		</ul>
	</nav>

	<!-- Bottom: Settings + Profile -->
	<div class="border-t py-2 px-2 space-y-1">
		<a
			href="/settings"
			class="btn-press relative flex h-10 items-center rounded-md text-sm transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground
				{isActive('/settings') ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium' : ''}"
			title={isCollapsed ? 'Settings' : undefined}
		>
			{#if isActive('/settings')}
				<span
					class="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r bg-primary"
				></span>
			{/if}
			<span class="flex w-14 shrink-0 items-center justify-center">
				<Settings class="h-5 w-5" />
			</span>
			{#if !isCollapsed}
				<span>Settings</span>
			{/if}
		</a>

		<!-- User Popover -->
		<Popover.Root>
			<Popover.Trigger
				class="btn-press flex h-12 w-full items-center rounded-md text-sm transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
			>
				<span class="flex w-14 shrink-0 items-center justify-center">
					<span
						class="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-xs font-medium"
					>
						{userInitials}
					</span>
				</span>
				{#if !isCollapsed}
					<div class="grid flex-1 text-left text-sm leading-tight">
						<span class="truncate font-semibold">
							{auth.user?.firstName}
							{auth.user?.lastName}
						</span>
						<span class="truncate text-xs text-muted-foreground">
							{auth.user?.email}
						</span>
					</div>
				{/if}
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
				<button
					class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground"
					disabled
				>
					<CreditCard class="h-4 w-4" />
					Billing
				</button>
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
