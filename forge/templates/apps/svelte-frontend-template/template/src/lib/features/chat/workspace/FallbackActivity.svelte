<script lang="ts">
	import type { WorkspaceActivity } from '../chat.types';

	let { activity }: { activity: WorkspaceActivity } = $props();
</script>

<div class="space-y-2 p-4" data-testid="fallback-activity">
	<p class="text-sm font-medium">Activity: {activity.activityType}</p>
	<pre
		class="max-h-96 overflow-auto rounded-md bg-muted p-3 font-mono text-xs whitespace-pre-wrap break-all"
	>{JSON.stringify(activity.content, null, 2)}</pre>
</div>
