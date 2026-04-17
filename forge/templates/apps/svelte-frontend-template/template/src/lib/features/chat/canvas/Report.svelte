<script lang="ts">
	import DOMPurify from 'dompurify';
	import { marked } from 'marked';
	import type { WorkspaceActivity } from '../chat.types';

	let { activity }: { activity: WorkspaceActivity } = $props();

	const title = $derived(
		typeof activity.content.title === 'string' ? activity.content.title : ''
	);
	const markdown = $derived(
		typeof activity.content.markdown === 'string'
			? activity.content.markdown
			: typeof activity.content.body === 'string'
				? activity.content.body
				: ''
	);

	const html = $derived.by(() => DOMPurify.sanitize(marked.parse(markdown, { async: false }) as string));
</script>

<article class="prose prose-sm dark:prose-invert max-w-none p-4" data-testid="canvas-report">
	{#if title}
		<h2>{title}</h2>
	{/if}
	{@html html}
</article>
