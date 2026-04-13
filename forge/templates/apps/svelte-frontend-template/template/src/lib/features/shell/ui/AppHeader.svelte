<script lang="ts">
	import { page } from '$app/stores';
	import { Sun, Moon, Monitor, ChevronRight, Sparkles } from 'lucide-svelte';
	import { Tooltip } from 'bits-ui';
	import { getSettingsStore } from '$lib/features/settings';
	import { getUiStore } from '$lib/features/shell';

	const settings = getSettingsStore();
	const ui = getUiStore();

	let themeMenuOpen = $state(false);

	const routeTitleMap: Record<string, string> = {
		'/': 'Home',
		'/profile': 'Profile',
		'/settings': 'Settings',
		// --- feature route titles ---
	};

	const breadcrumbs = $derived(() => {
		const pathname = $page.url.pathname;
		const crumbs: { label: string; href?: string }[] = [];

		if (pathname === '/') {
			crumbs.push({ label: 'Home' });
			return crumbs;
		}

		const segments = pathname.split('/').filter(Boolean);
		let currentPath = '';

		for (let i = 0; i < segments.length; i++) {
			currentPath += '/' + segments[i];
			const title = routeTitleMap[currentPath];
			const isLast = i === segments.length - 1;

			if (title) {
				crumbs.push({
					label: title,
					href: isLast ? undefined : currentPath
				});
			} else {
				crumbs.push({ label: 'Detail' });
			}
		}

		return crumbs;
	});

	const currentPageTitle = $derived(() => {
		const pathname = $page.url.pathname;
		return routeTitleMap[pathname] ?? 'Detail';
	});

	const ThemeIcon = $derived(
		settings.theme === 'dark' ? Moon : settings.theme === 'light' ? Sun : Monitor
	);
</script>

<header class="flex h-14 shrink-0 items-center gap-2 border-b px-4">
	<!-- Navigation: breadcrumbs on medium/desktop, title only on mobile -->
	{#if ui.isMobile}
		<span class="text-sm font-medium">{currentPageTitle()}</span>
	{:else}
		<nav class="flex items-center gap-1.5 text-sm">
			{#each breadcrumbs() as crumb, i}
				{#if i > 0}
					<ChevronRight class="h-3.5 w-3.5 text-muted-foreground" />
				{/if}
				{#if crumb.href}
					<a
						href={crumb.href}
						class="text-muted-foreground transition-colors hover:text-foreground"
					>
						{crumb.label}
					</a>
				{:else}
					<span class="font-medium">{crumb.label}</span>
				{/if}
			{/each}
		</nav>
	{/if}

	<div class="ml-auto flex items-center gap-2">
		<!-- AI Chat Button -->
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<button
						{...props}
						class="btn-press inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium text-ai-accent-foreground shadow-sm transition-all duration-200 hover:shadow-md hover:shadow-ai-accent/20"
						style="background: linear-gradient(to right, hsl(var(--ai-gradient-from)), hsl(var(--ai-gradient-to)))"
						onclick={() => ui.toggleChat()}
						aria-label="Open AI Chat"
						aria-expanded={ui.chatOpen}
						aria-controls="ai-chat-panel"
					>
						<Sparkles class="h-4 w-4 ai-sparkle" />
						<span class="hidden sm:inline">Ask AI</span>
					</button>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content
				class="z-50 rounded-md border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-md"
			>
				Ask AI
				<kbd class="ml-1.5 rounded bg-muted px-1 py-0.5 font-mono text-[10px]">Ctrl+J</kbd>
			</Tooltip.Content>
		</Tooltip.Root>

		<!-- Theme Switcher -->
		<div class="relative">
			<button
				class="btn-press inline-flex h-9 w-9 items-center justify-center rounded-lg text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground"
				title="Toggle theme"
				onclick={() => (themeMenuOpen = !themeMenuOpen)}
			>
				<ThemeIcon class="h-4 w-4" />
				<span class="sr-only">Toggle theme</span>
			</button>

			{#if themeMenuOpen}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					class="fixed inset-0 z-40"
					onclick={() => (themeMenuOpen = false)}
					onkeydown={(e) => e.key === 'Escape' && (themeMenuOpen = false)}
				></div>
				<div
					class="absolute right-0 top-full z-50 mt-1 min-w-[8rem] overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
				>
					<button
						class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
						onclick={() => {
							settings.setTheme('light');
							themeMenuOpen = false;
						}}
					>
						<Sun class="h-4 w-4" />
						Light
					</button>
					<button
						class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
						onclick={() => {
							settings.setTheme('dark');
							themeMenuOpen = false;
						}}
					>
						<Moon class="h-4 w-4" />
						Dark
					</button>
					<button
						class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
						onclick={() => {
							settings.setTheme('system');
							themeMenuOpen = false;
						}}
					>
						<Monitor class="h-4 w-4" />
						System
					</button>
				</div>
			{/if}
		</div>
	</div>
</header>
