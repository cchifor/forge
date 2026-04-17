<script lang="ts">
	import type { WorkspaceAction, WorkspaceActivity } from '../../chat.types';
	import { resolveWorkspaceComponent } from '../registry';

	let {
		activity,
		onAction
	}: { activity: WorkspaceActivity; onAction?: (a: WorkspaceAction) => void } = $props();

	const entry = $derived(resolveWorkspaceComponent(activity.activityType));
</script>

{#if entry}
	{@const Comp = entry.component}
	<Comp {activity} {onAction} />
{/if}
