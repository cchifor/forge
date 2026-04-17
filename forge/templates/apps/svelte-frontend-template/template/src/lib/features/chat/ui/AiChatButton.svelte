<script lang="ts">
	import { Sparkles } from 'lucide-svelte';
	import { getUiStore } from '$lib/features/shell/model/ui.svelte';

	const ui = getUiStore();

	function toggle() {
		ui.toggleChat();
	}

	$effect(() => {
		function onKey(e: KeyboardEvent) {
			if ((e.ctrlKey || e.metaKey) && (e.key === 'j' || e.key === 'J')) {
				e.preventDefault();
				toggle();
			}
		}
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	});
</script>

<button
	type="button"
	onclick={toggle}
	aria-label="Toggle AI chat (Ctrl+J)"
	title="AI chat (Ctrl+J)"
	class="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
	data-testid="ai-chat-button"
>
	<Sparkles class="h-4 w-4" aria-hidden="true" />
</button>
