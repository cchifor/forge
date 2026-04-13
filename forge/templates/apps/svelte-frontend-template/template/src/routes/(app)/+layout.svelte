<script lang="ts">
	import { goto } from '$app/navigation';
	import { getAuth } from '$lib/core';
	import { getUiStore, AppSidebar, AppHeader } from '$lib/features/shell';
	import { AiChat } from '$lib/features/chat';
	import BottomNav from '$lib/features/shell/ui/BottomNav.svelte';
	import ChatDrawer from '$lib/features/shell/ui/ChatDrawer.svelte';
	import ChatBottomSheet from '$lib/features/shell/ui/ChatBottomSheet.svelte';
	import VerticalSplitHandle from '$lib/features/shell/ui/VerticalSplitHandle.svelte';

	let { children } = $props();
	const auth = getAuth();
	const ui = getUiStore();

	$effect(() => {
		if (!auth.isLoading && !auth.isAuthenticated) {
			goto('/login');
		}
	});

	function handleKeydown(e: KeyboardEvent) {
		if ((e.metaKey || e.ctrlKey) && e.key === 'j') {
			e.preventDefault();
			ui.toggleChat();
		}
	}

	// Splitter drag logic for expanded chat
	function handleDragMove(clientX: number) {
		const chatPx = window.innerWidth - clientX;
		ui.setChatWidth(chatPx);
	}
</script>

<svelte:window onkeydown={handleKeydown} />

{#if auth.isAuthenticated}
	{#if ui.isMobile}
		<!-- COMPACT: Header + Content + BottomNav -->
		<div class="flex min-h-svh flex-col">
			<AppHeader />
			<main class="flex-1 overflow-y-auto p-4 pb-20">{@render children()}</main>
			<BottomNav />
		</div>
		{#if ui.chatOpen}
			<ChatBottomSheet bind:open={() => ui.chatOpen, (v) => { if (!v) ui.closeChat(); }}>
				<AiChat mode="sheet" />
			</ChatBottomSheet>
		{/if}
	{:else if ui.isMedium}
		<!-- MEDIUM: Collapsed sidebar + Content -->
		<div class="flex min-h-svh">
			<AppSidebar forceCollapsed />
			<div class="flex flex-1 flex-col min-w-0">
				<AppHeader />
				<main class="flex-1 overflow-y-auto p-4">{@render children()}</main>
			</div>
		</div>
		{#if ui.chatOpen}
			<ChatDrawer bind:open={() => ui.chatOpen, (v) => { if (!v) ui.closeChat(); }}>
				<AiChat mode="drawer" />
			</ChatDrawer>
		{/if}
	{:else}
		<!-- EXPANDED: Full sidebar + Content + Inline chat -->
		<div
			class="group/sidebar-wrapper flex min-h-svh"
			data-sidebar-state={ui.sidebarCollapsed ? 'collapsed' : 'expanded'}
		>
			<AppSidebar />
			<div class="flex flex-1 flex-col min-w-0">
				<AppHeader />
				<div class="flex flex-1 min-h-0">
					<main class="flex-1 overflow-y-auto p-4">{@render children()}</main>
					{#if ui.chatOpen}
						<VerticalSplitHandle ondragmove={handleDragMove} />
						<div
							style="width: {ui.chatWidth}px"
							class="flex-shrink-0 border-l overflow-hidden"
						>
							<AiChat mode="inline" />
						</div>
					{/if}
				</div>
			</div>
		</div>
	{/if}
{/if}
