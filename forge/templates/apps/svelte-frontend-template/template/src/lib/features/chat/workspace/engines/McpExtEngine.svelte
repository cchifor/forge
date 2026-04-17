<script lang="ts">
	import type { WorkspaceAction, WorkspaceActivity } from '../../chat.types';
	import { resolveWorkspaceComponent } from '../registry';

	// MCP extension activities render through the same component registry as
	// AG-UI activities. The engine layer exists so MCP-specific behaviors
	// (sandbox iframe, tool dispatch) can be added without touching the
	// activity widgets themselves.

	let {
		activity,
		onAction
	}: { activity: WorkspaceActivity; onAction?: (a: WorkspaceAction) => void } = $props();

	const entry = $derived(resolveWorkspaceComponent(activity.activityType));

	function dispatchAction(action: WorkspaceAction) {
		// MCP tool callouts mirror AG-UI submit semantics — the agent reducer
		// turns the answer back into an HTTP response.
		onAction?.(action);
	}
</script>

<div data-testid="mcp-ext-engine" data-activity-type={activity.activityType}>
	{#if entry}
		{@const Comp = entry.component}
		<Comp {activity} onAction={dispatchAction} />
	{/if}
</div>
