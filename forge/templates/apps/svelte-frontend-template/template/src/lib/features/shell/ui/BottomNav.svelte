<script lang="ts">
	import { page } from '$app/stores';
	import { Home, FolderOpen, User, Settings } from 'lucide-svelte';

	const navItems = [
		{ title: 'Home', url: '/', icon: Home },
		// --- feature nav items ---
		{ title: 'Profile', url: '/profile', icon: User },
		{ title: 'Settings', url: '/settings', icon: Settings }
	];

	function isActive(url: string) {
		if (url === '/') return $page.url.pathname === '/';
		return $page.url.pathname.startsWith(url);
	}
</script>

<nav class="fixed bottom-0 left-0 right-0 z-30 flex h-16 items-center border-t bg-background">
	{#each navItems as item}
		<a
			href={item.url}
			class="btn-press flex flex-1 flex-col items-center justify-center gap-1 py-2 transition-colors hover:text-foreground
				{isActive(item.url) ? 'text-primary' : 'text-muted-foreground'}"
		>
			<item.icon class="h-5 w-5" />
			<span class="text-xs font-medium">{item.title}</span>
		</a>
	{/each}
</nav>
