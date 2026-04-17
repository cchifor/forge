<script lang="ts">
	import { X } from 'lucide-svelte';
	import { getChatStore } from '$lib/features/chat';
	import type { WorkspaceAction } from '../chat.types';
	import { resolveWorkspaceComponent } from './registry';
	import AgUiEngine from './engines/AgUiEngine.svelte';
	import McpExtEngine from './engines/McpExtEngine.svelte';

	const chat = getChatStore();
	const activity = $derived(chat.workspaceActivity);
	const entry = $derived(activity ? resolveWorkspaceComponent(activity.activityType) : null);

	function handleAction(action: WorkspaceAction) {
		if (action.type === 'submit') {
			chat.respondToPrompt(JSON.stringify(action.data));
		}
	}
</script>

{#if activity && entry}
	<aside
		class="flex h-full w-full flex-col border-l border-border bg-background"
		aria-label={entry.label}
		data-testid="workspace-pane"
		data-activity-type={activity.activityType}
	>
		<div class="flex h-12 shrink-0 items-center justify-between border-b border-border px-3">
			<h3 class="text-sm font-medium">{entry.label}</h3>
			<button
				type="button"
				onclick={() => chat.clearWorkspaceActivity()}
				class="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
				aria-label="Close workspace"
			>
				<X class="h-4 w-4" />
			</button>
		</div>
		<div class="flex-1 overflow-y-auto">
			{#if activity.engine === 'mcp-ext'}
				<McpExtEngine {activity} onAction={handleAction} />
			{:else}
				<AgUiEngine {activity} onAction={handleAction} />
			{/if}
		</div>
	</aside>
{/if}
