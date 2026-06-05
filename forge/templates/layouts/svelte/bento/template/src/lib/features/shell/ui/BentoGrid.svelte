<script lang="ts">
	// BentoGrid — a presentational CSS-Grid wrapper for dashboard tiles.
	//
	// Generated dashboard pages compose this inside the standard <main> slot.
	// Tiles are plain children; apply `col-span-2` / `row-span-2` on a child to
	// create the asymmetric "bento" rhythm. Responsive column counts come from
	// Tailwind breakpoints: 1 col (mobile) -> 2 cols (sm, 640px) -> 4 cols (lg,
	// 1024px). These 640/1024 thresholds conveniently match the Svelte shell's
	// own breakpoints, but they remain an independent concern: the shell
	// breakpoints decide which chrome renders (sidebar vs. bottom nav vs. chat
	// mode); BentoGrid only governs the inner tile mosaic.
	//
	// Scope: layout-private. Intentionally NOT re-exported from shell/index.ts
	// (which is base-owned) — only the bento layout's generated dashboard pages
	// import it, so it ships with this overlay rather than the shared shell API.
	//
	// `auto-rows-[minmax(8rem,auto)]` sets a 128px (8rem) minimum row height so a
	// plain single-cell tile is never shorter than one comfortable card; tiles
	// with more content grow past it via the `auto` upper bound, and `row-span-2`
	// tiles span two such tracks to form the tall bento cells.
	//
	// CSS Grid is intentional here: the bento mosaic is the one place the layout
	// uses Grid; the surrounding app shell stays Flexbox.
	import type { Snippet } from 'svelte';

	let { children }: { children?: Snippet } = $props();
</script>

<div
	class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 auto-rows-[minmax(8rem,auto)]"
>
	{@render children?.()}
</div>
