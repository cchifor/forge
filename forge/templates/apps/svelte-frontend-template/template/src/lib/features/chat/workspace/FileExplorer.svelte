<script lang="ts">
	import { File, FileCode, FileText, Film, Image as ImageIcon, Music } from 'lucide-svelte';
	import type { WorkspaceAction, WorkspaceActivity } from '../chat.types';

	let {
		activity,
		onAction
	}: { activity: WorkspaceActivity; onAction?: (a: WorkspaceAction) => void } = $props();

	interface FileEntry {
		path: string;
		name: string;
		size?: number;
		type?: string;
	}

	const files = $derived.by<FileEntry[]>(() => {
		const raw = activity.content.files;
		return Array.isArray(raw) ? (raw as FileEntry[]) : [];
	});

	const description = $derived(
		typeof activity.content.description === 'string' ? activity.content.description : ''
	);

	function iconFor(file: FileEntry) {
		const t = (file.type ?? '').toLowerCase();
		if (t === 'image') return ImageIcon;
		if (t === 'video') return Film;
		if (t === 'audio') return Music;
		if (t === 'code') return FileCode;
		if (t === 'text') return FileText;
		const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
		if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) return ImageIcon;
		if (['mp4', 'mov', 'webm'].includes(ext)) return Film;
		if (['mp3', 'wav', 'ogg'].includes(ext)) return Music;
		if (['ts', 'js', 'svelte', 'py', 'rs', 'json'].includes(ext)) return FileCode;
		if (['txt', 'md', 'csv'].includes(ext)) return FileText;
		return File;
	}

	function fmtSize(bytes?: number) {
		if (bytes == null) return '';
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
	}

	function select(file: FileEntry) {
		onAction?.({ type: 'select_file', data: { path: file.path } });
	}
</script>

<div class="flex flex-col gap-1 p-4" data-testid="file-explorer">
	{#if description}
		<p class="mb-3 text-sm text-muted-foreground">{description}</p>
	{/if}
	{#if files.length === 0}
		<div class="py-8 text-center text-sm text-muted-foreground">No files available.</div>
	{:else}
		{#each files as file (file.path)}
			{@const Icon = iconFor(file)}
			<button
				type="button"
				class="flex items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted"
				onclick={() => select(file)}
			>
				<Icon class="h-4 w-4 shrink-0 text-muted-foreground" />
				<span class="flex-1 truncate text-sm">{file.name}</span>
				{#if file.size != null}
					<span class="shrink-0 text-xs text-muted-foreground">{fmtSize(file.size)}</span>
				{/if}
			</button>
		{/each}
	{/if}
</div>
